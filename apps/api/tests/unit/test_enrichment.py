from app.modules.enrichment.service import extract_apify_supplementary_fields, extract_supplementary_fields


def test_extracts_present_fields():
    tags = {
        "opening_hours": "Mo-Fr 09:00-18:00",
        "contact:email": "contato@example.com",
        "cuisine": "pizza",
    }
    assert extract_supplementary_fields(tags) == {
        "opening_hours": "Mo-Fr 09:00-18:00",
        "email": "contato@example.com",
        "cuisine": "pizza",
    }


def test_ignores_absent_fields():
    assert extract_supplementary_fields({}) == {}


def test_prefers_contact_prefixed_tag_over_bare_one():
    tags = {"contact:email": "contact-prefixed@example.com", "email": "bare@example.com"}
    assert extract_supplementary_fields(tags)["email"] == "contact-prefixed@example.com"


def test_falls_back_to_bare_tag_when_contact_prefixed_is_absent():
    tags = {"email": "bare@example.com"}
    assert extract_supplementary_fields(tags)["email"] == "bare@example.com"


def test_never_fabricates_a_value_for_an_unmapped_tag():
    tags = {"some_unrelated_osm_tag": "whatever"}
    assert extract_supplementary_fields(tags) == {}


def test_apify_extracts_opening_hours_and_category():
    apify_place = {
        "categoryName": "Restaurante",
        "openingHours": [
            {"day": "segunda-feira", "hours": "11:00 to 15:00"},
            {"day": "terça-feira", "hours": "11:00 to 15:00"},
        ],
    }
    result = extract_apify_supplementary_fields(apify_place)
    assert result["category"] == "Restaurante"
    assert "segunda-feira: 11:00 to 15:00" in result["opening_hours"]
    assert "terça-feira: 11:00 to 15:00" in result["opening_hours"]


def test_apify_ignores_absent_fields():
    assert extract_apify_supplementary_fields({}) == {}


def test_apify_never_fabricates_opening_hours_from_malformed_entries():
    apify_place = {"openingHours": [{"day": "segunda-feira"}, {"hours": "11:00 to 15:00"}]}
    result = extract_apify_supplementary_fields(apify_place)
    assert "opening_hours" not in result
