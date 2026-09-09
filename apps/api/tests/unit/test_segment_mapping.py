from app.modules.discovery.segment_mapping import (
    SEGMENT_TO_APIFY_SEARCH_TERM,
    get_apify_search_term,
)


def test_get_apify_search_term_uses_country_specific_term_when_mapped():
    """Real-world fix: searching the Portuguese term against a US city
    would return noise/nothing — the term must match the language actually
    used there."""
    assert get_apify_search_term(SEGMENT_TO_APIFY_SEARCH_TERM["restaurants"], "US") == "restaurant"


def test_get_apify_search_term_falls_back_to_br_for_unmapped_country():
    """Never a guessed translation for a country nobody's verified a real
    term for — falls back to the original, long-standing BR term. Japan is
    real and deliberately still unmapped for this test's purpose (no
    country here has ever been verified for the clinics/b2b_services
    segments, but restaurants now covers Portugal for real -- see the
    dedicated PT test below)."""
    assert (
        get_apify_search_term(SEGMENT_TO_APIFY_SEARCH_TERM["clinics"], "JP")
        == "clínica médica"
    )


def test_every_segment_has_a_br_fallback_term():
    """BR is the one guaranteed key — every segment must have it, since
    every other country's absence falls back to it."""
    for segment, terms in SEGMENT_TO_APIFY_SEARCH_TERM.items():
        assert "BR" in terms, f"{segment} has no BR fallback term"


def test_get_apify_search_term_covers_the_8_country_rotation_for_restaurants():
    """Fase 17: each of these was verified with a real Apify call against a
    real city in that country (see docs/DISCOVERY.md) before being trusted
    here, not just translated from memory — same discipline as the
    original BR/US entries."""
    restaurants = SEGMENT_TO_APIFY_SEARCH_TERM["restaurants"]
    assert get_apify_search_term(restaurants, "ES") == "restaurante"
    assert get_apify_search_term(restaurants, "PT") == "restaurante"
    assert get_apify_search_term(restaurants, "FR") == "restaurant"
    assert get_apify_search_term(restaurants, "GB") == "restaurant"
    assert get_apify_search_term(restaurants, "DE") == "Restaurant"
    assert get_apify_search_term(restaurants, "IT") == "ristorante"
