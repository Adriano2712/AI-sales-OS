import pytest

from app.modules.discovery.base import NATIONWIDE_CITY_SENTINEL, DiscoveryProviderError
from app.modules.discovery.providers.overpass import OverpassProvider, _first_present


def test_first_present_returns_first_matching_key_in_priority_order():
    tags = {"contact:phone": "111", "phone": "222"}
    assert _first_present(tags, "phone", "contact:phone") == "222"


def test_first_present_falls_back_when_priority_key_absent():
    tags = {"mobile": "333"}
    assert _first_present(tags, "phone", "contact:phone", "mobile") == "333"


def test_first_present_returns_none_when_no_key_matches():
    assert _first_present({}, "phone", "contact:phone") is None


def test_to_raw_company_finds_phone_under_mobile_tag():
    """Real bug found running against live Overpass data (Fase 3): a
    Votorantim restaurant's number was tagged `mobile`, not `phone` —
    _to_raw_company must check both."""
    element = {
        "type": "node",
        "id": 123,
        "tags": {"name": "Pastelaria Teste", "mobile": "+55 15 99601 2075"},
    }
    result = OverpassProvider._to_raw_company(element, "restaurants", "Votorantim", "SP", "BR")
    assert result.phone == "+55 15 99601 2075"


def test_to_raw_company_finds_website_under_url_tag():
    element = {
        "type": "node",
        "id": 456,
        "tags": {"name": "Restaurante Teste", "url": "https://example.com"},
    }
    result = OverpassProvider._to_raw_company(element, "restaurants", "Sorocaba", "SP", "BR")
    assert result.website == "https://example.com"


def test_to_raw_company_leaves_phone_and_website_none_when_absent():
    element = {"type": "node", "id": 789, "tags": {"name": "Sem Contato"}}
    result = OverpassProvider._to_raw_company(element, "restaurants", "Sorocaba", "SP", "BR")
    assert result.phone is None
    assert result.website is None


def test_to_raw_company_finds_instagram_under_contact_prefixed_tag():
    element = {
        "type": "node",
        "id": 111,
        "tags": {"name": "Restaurante Insta", "contact:instagram": "https://instagram.com/restauranteinsta"},
    }
    result = OverpassProvider._to_raw_company(element, "restaurants", "Sorocaba", "SP", "BR")
    assert result.instagram == "https://instagram.com/restauranteinsta"


def test_to_raw_company_leaves_instagram_none_when_absent():
    element = {"type": "node", "id": 789, "tags": {"name": "Sem Contato"}}
    result = OverpassProvider._to_raw_company(element, "restaurants", "Sorocaba", "SP", "BR")
    assert result.instagram is None


def test_build_query_constrains_city_boundary_to_country_area():
    """Real bug found running against live Overpass (post-Fase-10 San
    Antonio campaign): a bare city-name area match found a "San Antonio" in
    Makati, Philippines instead of Texas, because city names collide across
    countries. Filtering one `area` statement by another (`area[...]
    (area.country)`) turned out to be a silent no-op against the real API
    (confirmed live — same wrong Manila results came back). The working
    pattern filters the city's `relation`/`way` boundary elements by
    `(area.country)` first, then converts the match to an area with
    `map_to_area`."""
    query = OverpassProvider._build_query("San Antonio", "US", [("amenity", "restaurant")])
    assert 'area["ISO3166-1"="US"][admin_level=2]->.country;' in query
    assert 'relation["name"="San Antonio"]["boundary"="administrative"](area.country);' in query
    assert 'way["name"="San Antonio"]["boundary"="administrative"](area.country);' in query
    assert ".cityElements map_to_area->.searchArea;" in query


@pytest.mark.asyncio
async def test_search_rejects_nationwide_sentinel():
    """Overpass has no equivalent to Apify's whole-country search — a
    country-wide query against the shared free instance is a real overload
    risk (it already rate-limits at 3 back-to-back cities). Must fail
    cleanly, not attempt the query."""
    provider = OverpassProvider()
    with pytest.raises(DiscoveryProviderError):
        await provider.search("restaurants", NATIONWIDE_CITY_SENTINEL, "BR", "BR", 5)
