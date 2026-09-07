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
    term for — falls back to the original, long-standing BR term."""
    assert (
        get_apify_search_term(SEGMENT_TO_APIFY_SEARCH_TERM["restaurants"], "PT")
        == "restaurante"
    )


def test_every_segment_has_a_br_fallback_term():
    """BR is the one guaranteed key — every segment must have it, since
    every other country's absence falls back to it."""
    for segment, terms in SEGMENT_TO_APIFY_SEARCH_TERM.items():
        assert "BR" in terms, f"{segment} has no BR fallback term"
