import httpx

from app.modules.companies.service import NormalizedRawCompany
from app.modules.discovery.base import DiscoveryProvider, DiscoveryProviderError
from app.modules.discovery.segment_mapping import SEGMENT_TO_APIFY_SEARCH_TERM

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
    phoneUnformatted, website, street, placeId, permanentlyClosed, ...) were
    verified against a real, live run against this project's own Apify
    account before writing this — not guessed (see docs/DISCOVERY.md)."""

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
        search_term = SEGMENT_TO_APIFY_SEARCH_TERM.get(segment)
        if not search_term:
            raise DiscoveryProviderError(
                f"No Apify search-term mapping for segment '{segment}' — see "
                "app.modules.discovery.segment_mapping.SEGMENT_TO_APIFY_SEARCH_TERM"
            )

        # The actor's own docs recommend simple "City, Country" over
        # "City, State, Country" for more reliable area matching — verified
        # against the real input schema, not assumed.
        location_query = f"{city}, Brazil" if country == "BR" else f"{city}, {country}"

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
    def _to_raw_company(
        item: dict, segment: str, city: str, state: str, country: str
    ) -> NormalizedRawCompany:
        return NormalizedRawCompany(
            provider="apify",
            external_id=item.get("placeId"),
            name=item["title"],
            segment=segment,
            city=city,
            state=state,
            country=country,
            address=item.get("street") or item.get("address"),
            phone=item.get("phoneUnformatted") or item.get("phone"),
            website=item.get("website"),
            permanently_closed=bool(item.get("permanentlyClosed")),
            raw_data={"apify_place": item},
        )
