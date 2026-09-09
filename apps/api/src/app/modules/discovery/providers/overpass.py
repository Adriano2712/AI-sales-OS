import httpx

from app.modules.companies.domain_filters import is_excluded_website
from app.modules.companies.service import NormalizedRawCompany
from app.modules.discovery.base import NATIONWIDE_CITY_SENTINEL, DiscoveryProvider, DiscoveryProviderError
from app.modules.discovery.segment_mapping import SEGMENT_TO_OSM_TAGS

OVERPASS_API_URL = "https://overpass-api.de/api/interpreter"

# Overpass's server rejects generic HTTP-library user agents (confirmed:
# httpx's default "python-httpx/x.x" gets a 406) — it wants requests to
# self-identify, per Overpass's own usage guidelines. Without this, every
# request fails regardless of query correctness.
_USER_AGENT = "ai-sales-os-discovery/0.1 (internal tool; contact: project admin)"


class OverpassProvider(DiscoveryProvider):
    """Free, keyless (spec section 23). Known limitation: relies on the city
    existing as an OSM administrative boundary with that exact name — if it
    doesn't, this returns an empty list (not an error; that's a legitimate
    "no coverage here" outcome the Fase 9 experiment is partly designed to
    measure, see docs/DISCOVERY.md).

    City names collide across countries ("San Antonio" is a real place in
    Texas, Chile, and the Philippines, among others — confirmed the hard way
    running a real "San Antonio" campaign against country="US" and getting 3
    real restaurants back from Makati, Philippines). The city-name match is
    therefore always constrained to the target country first, using the
    ISO3166-1 tag OSM's own country boundaries carry — `country` is
    validated elsewhere (CampaignCreate) to always be a 2-letter code, so
    this is a real filter, not a guess.

    Getting the containment filter right took two tries against the real
    API: `area["name"=city](area.country)` — filtering one `area` statement
    by another — silently does nothing (Overpass only applies `(area.X)`
    containment to node/way/relation/nwr statements, not to another `area`
    statement; confirmed live — it kept returning the same wrong Manila
    results with that syntax). The working pattern queries the city's
    boundary as `relation`/`way` elements *filtered* by `(area.country)`,
    then converts the match to an area with `map_to_area` before the actual
    `nwr[...]` search runs against it. `state` is NOT similarly nested: it
    is only conventionally a 2-letter code in this project, never enforced
    (CampaignCreate allows up to 100 chars), and OSM's ISO3166-2 coverage on
    state/province boundaries is inconsistent enough worldwide that
    requiring it would risk turning existing working BR campaigns into
    silent empty results — country-level disambiguation is the fix for the
    actual bug observed, not a proxy for full precision."""

    name = "overpass"

    def __init__(self, api_url: str = OVERPASS_API_URL, timeout: float = 30.0) -> None:
        self._api_url = api_url
        self._timeout = timeout

    async def search(
        self, segment: str, city: str, state: str, country: str, limit: int
    ) -> list[NormalizedRawCompany]:
        if city == NATIONWIDE_CITY_SENTINEL:
            # A country-wide Overpass query against the shared free instance
            # would be a real overload risk (it already rate-limits at 3
            # cities back-to-back — see docs/DISCOVERY.md) — reject cleanly
            # rather than attempt it. Apify's own location search handles
            # whole-country natively; the job handler's existing
            # one-provider-fails-the-other-continues fallback means this
            # doesn't block the run.
            raise DiscoveryProviderError(
                "Overpass does not support nationwide search — use Apify for "
                f"city='{NATIONWIDE_CITY_SENTINEL}' campaigns (see docs/DISCOVERY.md)"
            )

        tags = SEGMENT_TO_OSM_TAGS.get(segment)
        if not tags:
            raise DiscoveryProviderError(
                f"No OSM tag mapping for segment '{segment}' — see "
                "app.modules.discovery.segment_mapping.SEGMENT_TO_OSM_TAGS"
            )

        query = self._build_query(city, country, tags)

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, headers={"User-Agent": _USER_AGENT}
            ) as client:
                response = await client.post(self._api_url, data={"data": query})
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise DiscoveryProviderError(f"Overpass request failed: {exc}") from exc

        elements = response.json().get("elements", [])
        results = [
            self._to_raw_company(element, segment, city, state, country)
            for element in elements
            if element.get("tags", {}).get("name")
        ]
        return results[:limit]

    @staticmethod
    def _build_query(city: str, country: str, tags: list[tuple[str, str]]) -> str:
        escaped_city = city.replace('"', '\\"')
        escaped_country = country.replace('"', '\\"')
        tag_clauses = "\n  ".join(
            f'nwr["{key}"="{value}"](area.searchArea);' for key, value in tags
        )
        return (
            "[out:json][timeout:25];\n"
            f'area["ISO3166-1"="{escaped_country}"][admin_level=2]->.country;\n'
            "(\n"
            f'  relation["name"="{escaped_city}"]["boundary"="administrative"](area.country);\n'
            f'  way["name"="{escaped_city}"]["boundary"="administrative"](area.country);\n'
            ")->.cityElements;\n"
            ".cityElements map_to_area->.searchArea;\n"
            f"(\n  {tag_clauses}\n);\n"
            "out center tags;"
        )

    @staticmethod
    def _to_raw_company(
        element: dict, segment: str, city: str, state: str, country: str
    ) -> NormalizedRawCompany:
        tags = element.get("tags", {})
        address_parts = [
            tags.get("addr:street"),
            tags.get("addr:housenumber"),
            tags.get("addr:suburb"),
        ]
        address = " ".join(part for part in address_parts if part) or None

        osm_type = element.get("type", "node")
        osm_id = element.get("id")

        # Real gap found running the 8-country rotation's Portugal
        # validation (Fase 18): "Kasa Mia" had `website=facebook.com/
        # KasaMialx` tagged directly in OSM — a business listing its own
        # Facebook page as its "website" tag is common, but that's not the
        # analyzable, owned site `Company.website` means for every
        # downstream consumer (website_analysis would score Facebook's own
        # page, not the business's). Filtered at the same domain_filters
        # list the search fallback already uses, not a separate guess.
        raw_website = _first_present(tags, "website", "contact:website", "url")
        website = None if is_excluded_website(raw_website) else raw_website

        return NormalizedRawCompany(
            provider="overpass",
            external_id=f"{osm_type}/{osm_id}",
            name=tags["name"],
            segment=segment,
            city=city,
            state=state,
            country=country,
            address=address,
            phone=_first_present(tags, "phone", "contact:phone", "mobile", "contact:mobile"),
            website=website,
            instagram=_first_present(tags, "contact:instagram", "instagram"),
            email=_first_present(tags, "contact:email", "email"),
            raw_data={"osm_tags": tags, "osm_type": osm_type, "osm_id": osm_id},
        )


def _first_present(tags: dict, *keys: str) -> str | None:
    """Real OSM data tags the same kind of fact under different keys
    depending on who mapped it (a phone number might be `phone`,
    `contact:phone`, or `mobile`) — confirmed the hard way when a real
    Votorantim restaurant's number was under `mobile` and the enrichment step
    asserted "no evidence of a phone" despite it being right there in
    `osm_tags`. Checking one key isn't enough; this checks several, in a
    fixed priority order, and returns the first that's actually present."""
    for key in keys:
        value = tags.get(key)
        if value:
            return value
    return None
