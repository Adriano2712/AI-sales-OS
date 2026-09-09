from app.modules.companies.domain_filters import domain, is_excluded_domain, is_excluded_website


def test_domain_strips_www_and_scheme():
    assert domain("https://www.lacocinadeirma.com/menu") == "lacocinadeirma.com"


def test_domain_handles_bare_host():
    assert domain("http://lacocinadeirma.com") == "lacocinadeirma.com"


def test_is_excluded_domain_matches_bare_domain():
    assert is_excluded_domain("facebook.com")


def test_is_excluded_domain_matches_any_subdomain():
    """Real bug caught during Fase 13's own validation: a real Brave Search
    hit for "La Cocina de Irma" (a business with no website field anywhere
    in Overpass/Apify) came back as `lacocinadeirma.restaurants-us.com` --
    a per-business subdomain of an excluded directory network. No two
    businesses share the same subdomain, so an exact `host in
    EXCLUDED_DOMAINS` check would silently miss this entire class of
    aggregator (see is_excluded_domain's docstring)."""
    assert is_excluded_domain("lacocinadeirma.restaurants-us.com")
    assert is_excluded_domain("m.facebook.com")


def test_is_excluded_domain_does_not_match_unrelated_domain():
    assert not is_excluded_domain("lacocinadeirma.com")
    # Real domain must not falsely match by simple substring -- a genuine
    # business domain that merely *contains* an excluded domain's name
    # (not as a real subdomain relationship) is never a false positive.
    assert not is_excluded_domain("notfacebook.com")


def test_is_excluded_domain_matches_a_known_multinational_chains_other_tld():
    """Real gap found during Fase 18's UK/London validation: "Nadri"
    resolved to tripadvisor.co.uk, a country-code TLD variant the exact
    tripadvisor.com entry can't catch -- TripAdvisor (and any other
    confirmed multinational chain) runs a separate TLD per market, and the
    8-country rotation makes hitting another one a near-certainty."""
    assert is_excluded_domain("tripadvisor.co.uk")
    assert is_excluded_domain("tripadvisor.fr")


def test_is_excluded_domain_multinational_label_match_is_exact_not_substring():
    assert not is_excluded_domain("nottripadvisor.com")


def test_is_excluded_domain_matches_resmio_subdomain():
    """Real gap found in the first unattended production run of the
    country rotation (Berlin): "Bep of Meo" resolved to
    pages.resmio.com/bep-of-meo/de -- a subdomain of the reservation
    platform, not the bare domain -- same subdomain-matching need as
    lacocinadeirma.restaurants-us.com above."""
    assert is_excluded_domain("pages.resmio.com")


def test_is_excluded_domain_matches_restaurantguru_across_tlds():
    """restaurantguru.com was excluded from Portugal validation;
    restaurantguru.it turned up separately during Italy validation -- a
    second real sighting confirming it's the same multinational network,
    not a guess, so it joined the same registrable-label matching as
    tripadvisor rather than being listed one TLD at a time."""
    assert is_excluded_domain("restaurantguru.it")


def test_is_excluded_website_matches_a_full_url():
    """Real gap found during Fase 18's Portugal validation: Overpass/Apify
    themselves sometimes report a Facebook page directly as `website` in
    their own raw data ("Kasa Mia" -> facebook.com/KasaMialx) -- this must
    be caught at the same source discovery providers read `website` from,
    not just in the separate search-fallback path."""
    assert is_excluded_website("https://www.facebook.com/KasaMialx")


def test_is_excluded_website_accepts_a_real_owned_domain():
    assert not is_excluded_website("https://www.casamingo.es/")


def test_is_excluded_website_handles_none():
    assert not is_excluded_website(None)
