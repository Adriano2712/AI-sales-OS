from app.modules.discovery.base import NATIONWIDE_CITY_SENTINEL
from app.modules.discovery.providers.apify import ApifyProvider

# Real fields, verified against a live run against this project's own Apify
# account (compass/crawler-google-places) before writing the parser — not
# guessed. Trimmed to what the parser actually reads.
_REAL_ITEM_SAMPLE = {
    "title": "Restaurante da Fazenda",
    "categoryName": "Restaurante",
    "address": "Estrada Heitor Cury, 171, SP-270, 105, Sorocaba - SP, 18052-775, Brasil",
    "street": "Estrada Heitor Cury, 171, SP-270, 105",
    "city": "Sorocaba",
    "state": "SP",
    "countryCode": "BR",
    "website": "https://www.facebook.com/RestauranteDaFazendaSorocaba/",
    "phone": "+55 15 3217-4006",
    "phoneUnformatted": "+551532174006",
    "permanentlyClosed": False,
    "temporarilyClosed": False,
    "placeId": "ChIJpZ76ALCLxZQRd_wgpgmUd3o",
}


def test_to_raw_company_maps_real_fields():
    result = ApifyProvider._to_raw_company(_REAL_ITEM_SAMPLE, "restaurants", "Sorocaba", "SP", "BR")
    assert result.provider == "apify"
    assert result.external_id == "ChIJpZ76ALCLxZQRd_wgpgmUd3o"
    assert result.name == "Restaurante da Fazenda"
    assert result.address == "Estrada Heitor Cury, 171, SP-270, 105"
    assert result.phone == "+551532174006"  # prefers phoneUnformatted
    assert result.website == "https://www.facebook.com/RestauranteDaFazendaSorocaba/"
    assert result.permanently_closed is False
    assert result.raw_data == {"apify_place": _REAL_ITEM_SAMPLE}


def test_to_raw_company_falls_back_to_formatted_phone_when_unformatted_absent():
    item = {**_REAL_ITEM_SAMPLE, "phoneUnformatted": None, "phone": "+55 15 3217-4006"}
    result = ApifyProvider._to_raw_company(item, "restaurants", "Sorocaba", "SP", "BR")
    assert result.phone == "+55 15 3217-4006"


def test_to_raw_company_falls_back_to_full_address_when_street_absent():
    item = {**_REAL_ITEM_SAMPLE, "street": None}
    result = ApifyProvider._to_raw_company(item, "restaurants", "Sorocaba", "SP", "BR")
    assert result.address == _REAL_ITEM_SAMPLE["address"]


def test_to_raw_company_leaves_phone_and_website_none_when_absent():
    item = {"title": "Sem Contato", "placeId": "abc"}
    result = ApifyProvider._to_raw_company(item, "restaurants", "Sorocaba", "SP", "BR")
    assert result.phone is None
    assert result.website is None
    assert result.permanently_closed is False


def test_to_raw_company_flags_permanently_closed():
    item = {**_REAL_ITEM_SAMPLE, "permanentlyClosed": True}
    result = ApifyProvider._to_raw_company(item, "restaurants", "Sorocaba", "SP", "BR")
    assert result.permanently_closed is True


def test_to_raw_company_prefers_real_place_city_over_campaign_city():
    """Needed for nationwide search (every result would otherwise be
    stamped city="BRASIL"), and more accurate generally — a search near a
    city boundary can legitimately return a neighboring city's business."""
    result = ApifyProvider._to_raw_company(
        _REAL_ITEM_SAMPLE, "restaurants", NATIONWIDE_CITY_SENTINEL, "BR", "BR"
    )
    assert result.city == "Sorocaba"
    assert result.state == "SP"


def test_to_raw_company_falls_back_to_campaign_city_when_item_lacks_one():
    item = {**_REAL_ITEM_SAMPLE, "city": None, "state": None}
    result = ApifyProvider._to_raw_company(item, "restaurants", "Votorantim", "SP", "BR")
    assert result.city == "Votorantim"
    assert result.state == "SP"


def test_build_location_query_city_scoped():
    assert ApifyProvider._build_location_query("Sorocaba", "BR") == "Sorocaba, Brazil"
    assert ApifyProvider._build_location_query("Lisboa", "PT") == "Lisboa, PT"


def test_build_location_query_nationwide_sentinel():
    assert ApifyProvider._build_location_query(NATIONWIDE_CITY_SENTINEL, "BR") == "Brazil"
