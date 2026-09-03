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
