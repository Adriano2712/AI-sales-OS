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
# (`searchStringsArray`), not a tag vocabulary, so this maps our segment to a
# Portuguese search term a real user would type. An unmapped segment raises
# DiscoveryProviderError, same as the OSM side.
SEGMENT_TO_APIFY_SEARCH_TERM: dict[str, str] = {
    "restaurants": "restaurante",
    "clinics": "clínica médica",
    "b2b_services": "empresa de serviços",
}
