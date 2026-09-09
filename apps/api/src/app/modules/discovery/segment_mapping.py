"""Segment -> OpenStreetMap tag mapping for the Overpass provider.

This is a technical translation table (business "segment" string -> OSM's own
tagging vocabulary), not the campaign-level configuration spec section 9 says
must stay code-free (cities, target quantities, which segments a campaign
targets — those remain free text/config, see Campaign.segment). Overpass
simply has no concept of "restaurants" without an OSM tag, so *some* mapping
has to live somewhere; keeping it isolated here, one dict, is the containment
for that necessity.

Extend by adding an entry — no other code changes needed, the Overpass
provider iterates whatever's here. An unmapped segment raises
DiscoveryProviderError with a clear message rather than silently searching
for nothing.
"""

SEGMENT_TO_OSM_TAGS: dict[str, list[tuple[str, str]]] = {
    "restaurants": [
        ("amenity", "restaurant"),
        ("amenity", "fast_food"),
    ],
    "clinics": [
        ("amenity", "clinic"),
        ("amenity", "doctors"),
        ("healthcare", "clinic"),
    ],
    "b2b_services": [
        ("office", "company"),
        ("office", "consulting"),
        ("office", "it"),
    ],
}

# Same containment idea as SEGMENT_TO_OSM_TAGS above, for Apify's Google Maps
# Scraper (compass/crawler-google-places): it searches by free-text term
# (`searchStringsArray`), not a tag vocabulary — so the term has to be a real
# word in the language people (and Google) actually use in that country, not
# just a translation of the segment name. This project's original campaigns
# were all Brazil-only, so "BR" is the one guaranteed key per segment and the
# fallback for any country without its own real, checked term (see
# get_apify_search_term) — never a guessed translation for an unmapped
# country. An unmapped segment raises DiscoveryProviderError, same as the
# OSM side.
# Fase 17 (8-country rotation, restaurants only for now): each of these 6
# new entries was verified with a real Apify call against a real city in
# that country before being trusted here (see docs/DISCOVERY.md) — not
# just translated from memory. clinics/b2b_services still have no verified
# term beyond BR/US and correctly fall back to BR until they're actually
# tested the same way (spec section 86 — don't invent evidence, including
# an untested translation, for a country nobody's checked yet).
SEGMENT_TO_APIFY_SEARCH_TERM: dict[str, dict[str, str]] = {
    "restaurants": {
        "BR": "restaurante",
        "US": "restaurant",
        "ES": "restaurante",
        "PT": "restaurante",
        "FR": "restaurant",
        "GB": "restaurant",
        "DE": "Restaurant",
        "IT": "ristorante",
    },
    "clinics": {"BR": "clínica médica", "US": "medical clinic"},
    "b2b_services": {"BR": "empresa de serviços", "US": "professional services company"},
}


def get_apify_search_term(segment_terms: dict[str, str], country: str) -> str:
    """Pure — real country-specific term when we have one checked and
    mapped, otherwise the original BR/Portuguese term (this project's
    long-standing default) rather than inventing a translation for a
    country nobody's verified a real search term for yet."""
    return segment_terms.get(country, segment_terms["BR"])
