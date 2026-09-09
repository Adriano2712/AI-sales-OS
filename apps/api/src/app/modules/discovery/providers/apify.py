import httpx

from app.modules.companies.domain_filters import is_excluded_website
from app.modules.companies.service import NormalizedRawCompany
from app.modules.discovery.base import NATIONWIDE_CITY_SENTINEL, DiscoveryProvider, DiscoveryProviderError
from app.modules.discovery.segment_mapping import SEGMENT_TO_APIFY_SEARCH_TERM, get_apify_search_term

_APIFY_API_URL = "https://api.apify.com/v2"

# Apify's own hard cap on a synchronous run before it returns 408 (per
# https://docs.apify.com/api/v2/act-run-sync-get-dataset-items-post) — the
# `timeout` we pass Apify stays a little under this so *we* get a clean
# DiscoveryProviderError instead of an ambiguous 408 body.
_APIFY_RUN_TIMEOUT_SECONDS = 280


class ApifyProvider(DiscoveryProvider):
    """Second discovery source, alongside OSM/Overpass — OSM + Apify, not
    OSM replaced by Apify. Uses the "Google Maps Scraper" actor
    (compass/crawler-google-places by default, configurable via
    settings.apify_discovery_actor). Field names below (title, phone,
    phoneUnformatted, website, street, placeId, permanentlyClosed,
    totalScore, reviewsCount, ...) were verified against a real, live run
    against this project's own Apify account before writing this — not
    guessed (see docs/DISCOVERY.md). No Instagram/Facebook handle field
    exists anywhere in this actor's real payload (confirmed by inspecting
    41 real captured results, Fase 4) — social intelligence for Apify-
    sourced companies stays None rather than being invented."""

    name = "apify"

    def __init__(
        self,
        api_token: str,
        actor_id: str = "compass/crawler-google-places",
        timeout: float = 300.0,
    ) -> None:
        self._api_token = api_token
        self._actor_id = actor_id
        self._timeout = timeout

    async def search(
        self, segment: str, city: str, state: str, country: str, limit: int
    ) -> list[NormalizedRawCompany]:
        segment_terms = SEGMENT_TO_APIFY_SEARCH_TERM.get(segment)
        if not segment_terms:
            raise DiscoveryProviderError(
                f"No Apify search-term mapping for segment '{segment}' — see "
                "app.modules.discovery.segment_mapping.SEGMENT_TO_APIFY_SEARCH_TERM"
            )
        # Real-world fix: searching "restaurante" (Portuguese) against a US
        # city returns noise/nothing — the term has to match the language
        # actually used there. Falls back to the original BR term for any
        # country without its own checked mapping.
        search_term = get_apify_search_term(segment_terms, country)

        location_query = self._build_location_query(city, country)

        run_input = {
            "searchStringsArray": [search_term],
            "locationQuery": location_query,
            "maxCrawledPlacesPerSearch": limit,
            "language": "pt-BR",
        }

        actor_path = self._actor_id.replace("/", "~")
        url = f"{_APIFY_API_URL}/actors/{actor_path}/run-sync-get-dataset-items"

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    url,
                    # Token goes in the Authorization header, never the URL —
                    # a query-string token ends up verbatim in any request
                    # logging (httpx's own INFO-level "HTTP Request: {method}
                    # {url} ..." line includes the full URL) — confirmed the
                    # hard way against this project's real worker log before
                    # this fix (spec section 6: token must never reach logs).
                    headers={"Authorization": f"Bearer {self._api_token}"},
                    params={"timeout": _APIFY_RUN_TIMEOUT_SECONDS},
                    json=run_input,
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise DiscoveryProviderError(f"Apify request failed: {exc}") from exc

        items = response.json()
        results = [
            self._to_raw_company(item, segment, city, state, country)
            for item in items
            if item.get("title")
        ]
        return results[:limit]

    @staticmethod
    def _build_location_query(city: str, country: str) -> str:
        # The actor's own docs recommend simple "City, Country" over
        # "City, State, Country" for more reliable area matching — verified
        # against the real input schema, not assumed. The nationwide sentinel
        # is the one case where the actor's docs say to pass the country
        # alone ("you can just set the whole country... it intelligently
        # splits it into subregions internally").
        if city == NATIONWIDE_CITY_SENTINEL:
            return "Brazil" if country == "BR" else country
        return f"{city}, Brazil" if country == "BR" else f"{city}, {country}"

    @staticmethod
    def _to_raw_company(
        item: dict, segment: str, city: str, state: str, country: str
    ) -> NormalizedRawCompany:
        # Prefer the real per-place city/state Apify already returns over
        # the campaign's nominal target — necessary for the nationwide
        # sentinel (every result would otherwise be stamped city="BRASIL"),
        # and more accurate generally: a search near a city boundary can
        # legitimately return a neighboring city's business.
        real_city = item.get("city") or city
        real_state = item.get("state") or state
        # Same real gap Overpass had (Fase 18, Portugal validation): a
        # Facebook/Instagram/etc. URL reported as `website` isn't the
        # business's own analyzable site — filtered at the shared
        # domain_filters list, not a separate guess.
        raw_website = item.get("website")
        website = None if is_excluded_website(raw_website) else raw_website
        return NormalizedRawCompany(
            provider="apify",
            external_id=item.get("placeId"),
            name=item["title"],
            segment=segment,
            city=real_city,
            state=real_state,
            country=country,
            address=item.get("street") or item.get("address"),
            phone=item.get("phoneUnformatted") or item.get("phone"),
            website=website,
            permanently_closed=bool(item.get("permanentlyClosed")),
            google_place_id=item.get("placeId"),
            google_rating=item.get("totalScore"),
            google_review_count=item.get("reviewsCount"),
            raw_data={"apify_place": item},
        )
