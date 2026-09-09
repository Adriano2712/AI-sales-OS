"""Domains that are never a business's own website — shared between
discovery providers (Overpass/Apify sometimes report a Facebook/Instagram
page directly as `website` in their own raw data) and the website search
fallback (enrichment/website_search.py). Lives here, not in either of
those modules, because both depend on `companies` already — putting it in
either provider-side or enrichment-side module would create a circular
import with the other.

A hit on one of these is real evidence the business exists online, but
never proof of an *owned* website — directories, social platforms, review
aggregators, and delivery marketplaces are never a business's own site
(spec section 86: don't invent what wasn't verified). `Company.website`
means "the business's own domain" for every downstream consumer
(website_analysis crawls and scores *this* page as if it were the
business's own site) — so this same definition has to be enforced
wherever a `website` value first enters the system, not just in one of
the two places it can come from.
"""

from urllib.parse import urlparse

# Grown reactively from real findings (see docs/DISCOVERY.md's Fase 13/17
# validations), never preemptively guessed — expect this to need more
# entries as more of these networks get hit for real.
EXCLUDED_DOMAINS = frozenset(
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
        # website of its own, not that the search is failing.
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
        # directories for other cities under similar names.
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
        # Confirmed the hard way (Fase 18, real Portugal/Lisboa validation
        # of the 8-country rotation): a per-business "spots" directory
        # page (`/spots/europe/portugal/.../restaurante-das-marias-.../
        # menu`), same shared-domain-many-businesses shape as every other
        # entry here.
        "novacircle.com",
        # Same Portugal validation, a different company ("Kasa Mia"): a
        # real European restaurant reservation/review platform (the
        # OpenTable/Resy of Europe), not the restaurant's own site.
        "thefork.com",
        # Same "Kasa Mia" search, next result after excluding thefork.com:
        # a real international restaurant review/directory site (the
        # Yelp/TripAdvisor of the restaurant-specific niche).
        "restaurantguru.com",
        # Same "Kasa Mia" search — inspecting the raw unfiltered top 10
        # (every existing exclusion applied, still nothing plausible)
        # showed every single result was a review/directory/social site.
        # Real evidence this business genuinely has no website of its own
        # (same pattern as "La Cocina de Irma", Fase 13): an AI-summarized
        # review aggregator, a car-navigation POI/restaurant directory
        # (Michelin's), a Portuguese lifestyle/listings magazine, a
        # global city-guide directory, and a menu-aggregator site.
        "trustthecrowd.com",
        "viamichelin.com",
        "lifecooler.com",
        "cityseeker.com",
        "menuweb.menu",
    }
)


def domain(url: str) -> str:
    """example.com from https://www.example.com/path, host-only, lowercased,
    `www.` stripped. Returns "" for anything that doesn't parse to a real
    host, rather than guessing."""
    host = urlparse(url if "://" in url else f"//{url}").netloc.lower()
    return host[4:] if host.startswith("www.") else host


def is_excluded_domain(host: str) -> bool:
    """Matches the bare domain (facebook.com) and any subdomain of it
    (m.facebook.com, business.facebook.com) — a real bug caught during
    Fase 13's own validation: a directory network's per-business subdomain
    (`lacocinadeirma.restaurants-us.com`) would silently pass an exact
    `host in EXCLUDED_DOMAINS` membership check, since no two businesses
    share the same subdomain."""
    return any(host == excluded or host.endswith(f".{excluded}") for excluded in EXCLUDED_DOMAINS)


def is_excluded_website(url: str | None) -> bool:
    """Convenience wrapper for the common case (a raw `website` string,
    possibly None) — used directly by discovery providers deciding whether
    to trust a `website` value Overpass/Apify reported on their own,
    before it ever becomes `NormalizedRawCompany.website`."""
    if not url:
        return False
    return is_excluded_domain(domain(url))
