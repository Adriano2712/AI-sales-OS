import uuid
from datetime import UTC, datetime

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.modules.companies.models import Company, CompanySource
from app.modules.companies.service import normalize_name
from app.modules.evidence.enums import EvidenceCategory, EvidenceConfidence, EvidencePolarity
from app.modules.evidence.service import get_or_create_evidence

logger = get_logger(job_type="ENRICHMENT")

_BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"

# A hit on one of these is real evidence the business exists online, but
# never proof of an *owned* website — directories, social platforms, review
# aggregators, and delivery marketplaces are never a business's own site
# (spec section 86: don't invent what wasn't verified). Overpass/Apify's own
# `website` field already means "the business's own domain" — this fallback
# has to mean the same thing, or it would silently redefine what
# `Company.website` means for every downstream consumer (website_analysis
# scores *this* page as if it were the business's own site).
_EXCLUDED_DOMAINS = frozenset(
    {
        "facebook.com",
        "instagram.com",
        "twitter.com",
        "x.com",
        "linkedin.com",
        "yelp.com",
        "tripadvisor.com",
        "foursquare.com",
        "opentable.com",
        "doordash.com",
        "ubereats.com",
        "grubhub.com",
        "postmates.com",
        "mapquest.com",
        "maps.google.com",
        "google.com",
        "bing.com",
        "yellowpages.com",
        "bbb.org",
        "indeed.com",
        "glassdoor.com",
        "zomato.com",
        "menupix.com",
        "allmenus.com",
        "waze.com",
        "apple.com",
        "yalp.com",
        "nextdoor.com",
        "wikipedia.org",
        # Confirmed the hard way (Fase 13, real Chicago validation): both
        # are subdomain-per-business directory/listing networks, not any
        # individual business's own domain. "La Cocina de Irma" (a real
        # independent restaurant with no website field anywhere in
        # Overpass/Apify) resolved to `lacocinadeirma.restaurants-us.com`
        # on the first real Brave Search call, then to
        # `la-cocina-de-irma.goto-where.com` after excluding the first —
        # strong evidence this specific business may genuinely have no
        # website of its own, not that the search is failing. This list is
        # grown reactively from real findings like these, not preemptively
        # guessed — expect it to need more entries as more of these
        # networks get hit for real.
        "restaurants-us.com",
        "goto-where.com",
        "weeblyte.com",
        "local.yahoo.com",
        # Confirmed the hard way (Fase 13, real Denver validation): a
        # downtown-area business directory ("250+ stores... restaurants,
        # bars, hotels, and services" per its own homepage), not the
        # business's own site — matched "Cactus Club" via a URL path
        # (`/Business/Cactus-Club/1621-Blake-Street-...`) that embeds the
        # address, the same per-business-page-on-one-shared-domain shape as
        # every other entry in this list. The site itself links to sibling
        # directories for other cities under similar names — expect more
        # of this same family to surface in future validations.
        "denverdowntown.com",
        # Same real Denver "Cactus Club" search — inspecting the raw
        # unfiltered top 10 (once every existing exclusion was applied and
        # still nothing plausible was found) surfaced these five more, none
        # a business's own site: a stock-photo library, a sibling of
        # denverdowntown.com for a different named district (same operator,
        # same `/Business/<name>/<address>` URL shape), a nonprofit/
        # organization data aggregator, a public library historical
        # archive, an architecture-history database, and a private-clubs
        # directory.
        "gettyimages.com",
        "the16thstreetmall.com",
        "causeiq.com",
        "archives.denverlibrary.org",
        "sah-archipedia.org",
        "cmac.ws",
    }
)

# Bounded to a handful of top results — this is a fallback lookup, not a
# general web crawl. Each result costs the same one API call regardless of
# `num`, so there's no separate cost lever here (see docs/DISCOVERY.md).
_MAX_RESULTS = 5
_REQUEST_TIMEOUT_SECONDS = 8.0


class WebsiteSearchError(Exception):
    """Raised for a request/response failure — callers treat this as
    "couldn't determine a website this way" (log and move on), the same
    degrade-gracefully posture as every other optional provider in this
    codebase (ApifyProvider et al), never a reason to fail discovery."""


def _domain(url: str) -> str:
    from urllib.parse import urlparse

    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _is_excluded_domain(host: str) -> bool:
    """Matches the bare domain (facebook.com) and any subdomain of it
    (m.facebook.com, business.facebook.com) — a real bug caught during this
    phase's own validation: "La Cocina de Irma" resolved to
    `lacocinadeirma.restaurants-us.com` (a per-business subdomain of an
    excluded aggregator), which a bare `host in _EXCLUDED_DOMAINS`
    membership check would have silently missed (no two businesses share
    the same subdomain, so exact-match against the full host can never
    catch this class of directory network)."""
    return any(host == excluded or host.endswith(f".{excluded}") for excluded in _EXCLUDED_DOMAINS)


def _is_plausible_own_site(company_name: str, title: str, snippet: str) -> bool:
    """Deliberately strict: accept only when the company's own name (after
    the same normalization identity-resolution already uses — lowercase, no
    accents/punctuation) appears verbatim in the result's title or snippet.
    A missed real website (still reported as "not found") is an acceptable
    cost; confidently linking the WRONG business's website to a real
    prospect is not (spec section 35 — never invent, including implicitly
    via a bad fuzzy match)."""
    normalized_name = normalize_name(company_name)
    if not normalized_name:
        return False
    combined = normalize_name(f"{title} {snippet}")
    return normalized_name in combined


async def search_company_website(
    company_name: str, city: str, state: str
) -> tuple[str, str, str] | None:
    """Real Brave Search API call — returns (url, title, snippet) for the
    first result that plausibly belongs to this company and isn't a known
    directory/social/aggregator domain, or None if nothing plausible was
    found. Never raises for a "no result" outcome; raises WebsiteSearchError
    only for a genuine request failure, which callers
    (find_website_via_search) already treat as non-fatal.

    Google Custom Search was the original choice here but turned out
    unusable for this: Google retired "search the entire web" for any
    engine created from 2026-01-20 onward — new engines are hard-limited to
    an explicit list of up to 50 pre-chosen domains, which defeats the
    purpose of finding an *unknown* business's website (confirmed against
    Google's own support docs, not assumed). Brave Search API is a real,
    actively maintained general-web search API with no such restriction."""
    settings = get_settings()
    api_key = settings.brave_search_api_key
    if not api_key:
        return None

    query = f'"{company_name}" {city} {state}'
    params: dict[str, str | int] = {"q": query, "count": _MAX_RESULTS}
    headers = {"Accept": "application/json", "X-Subscription-Token": api_key}

    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.get(_BRAVE_SEARCH_URL, params=params, headers=headers)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise WebsiteSearchError(f"Brave Search request failed: {exc}") from exc

    results = response.json().get("web", {}).get("results", [])
    for item in results:
        url = item.get("url")
        if not url:
            continue
        if _is_excluded_domain(_domain(url)):
            continue
        title = item.get("title", "")
        snippet = item.get("description", "")
        if _is_plausible_own_site(company_name, title, snippet):
            return url, title, snippet

    return None


async def find_website_via_search(
    db: AsyncSession, tenant_id: uuid.UUID, company: Company
) -> bool:
    """Fase 13: fallback for when Overpass/Apify's own `website` field is
    empty — a real gap found running against a real Chicago campaign (spec
    section 86 in reverse: OSM/Google Maps not having the field doesn't mean
    the business has no website, just that neither of *those two* sources
    has it linked). Only ever called when `company.website` is still None
    after discovery+enrichment (see jobs/handlers/discovery.py) — never
    overwrites a value a primary source already provided.

    Optional by design, same degrade-gracefully pattern as ApifyProvider:
    unset credentials -> quietly does nothing, discovery proceeds exactly as
    it did before this existed. Any request failure is caught and logged,
    never propagated -- a slow/broken search API must not stall or fail the
    company's discovery processing (see the try/except this is called from)."""
    try:
        found = await search_company_website(company.name, company.city, company.state)
    except WebsiteSearchError as exc:
        logger.error("website_search_failed", company_id=str(company.id), error=str(exc))
        return False

    if found is None:
        return False

    url, title, snippet = found
    company.website = url

    db.add(
        CompanySource(
            tenant_id=tenant_id,
            company_id=company.id,
            provider="brave_search",
            external_id=url,
            source_url=url,
            collected_at=datetime.now(UTC),
            data={"query_name": company.name, "title": title, "snippet": snippet},
        )
    )

    # A distinct claim from enrich_company's own "No public evidence of a
    # website was found" (already recorded by the time this runs) — kept
    # side by side rather than overwritten, an honest record of what was
    # known at each point rather than erasing the earlier UNKNOWN state.
    await get_or_create_evidence(
        db,
        tenant_id,
        company.id,
        claim=f"website (via busca web): {url}",
        source="brave_search",
        confidence=EvidenceConfidence.MEDIUM,
        polarity=EvidencePolarity.POSITIVE,
        category=EvidenceCategory.CONTACTABILITY,
        source_url=url,
        supporting_data={"field": "website", "value": url, "title": title},
    )

    logger.info("website_found_via_search", company_id=str(company.id), url=url)
    return True
