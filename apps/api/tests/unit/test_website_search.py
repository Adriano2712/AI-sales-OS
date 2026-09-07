from app.modules.enrichment.website_search import _domain, _is_excluded_domain, _is_plausible_own_site


def test_domain_strips_www_and_scheme():
    assert _domain("https://www.lacocinadeirma.com/menu") == "lacocinadeirma.com"


def test_domain_handles_bare_host():
    assert _domain("http://lacocinadeirma.com") == "lacocinadeirma.com"


def test_is_plausible_own_site_accepts_exact_name_in_title():
    """Real case (Fase 13): Overpass/Apify had no `website` field for this
    business at all, but a plain web search for it turns up a real site
    whose title contains its name verbatim."""
    assert _is_plausible_own_site(
        "La Cocina de Irma", "La Cocina de Irma - Authentic Mexican Food", ""
    )


def test_is_plausible_own_site_accepts_name_in_snippet_when_title_is_generic():
    assert _is_plausible_own_site(
        "La Cocina de Irma", "Home", "Welcome to La Cocina de Irma, family owned since 1998."
    )


def test_is_plausible_own_site_ignores_accents_and_case():
    assert _is_plausible_own_site("Zora Kafana", "ZORA KAFANA — Chicago", "")


def test_is_plausible_own_site_rejects_unrelated_business():
    """The strict, deliberate cost of this design: a real site for a
    different business never gets linked to the wrong prospect (spec
    section 35), even at the cost of missing some real matches whose title
    doesn't literally contain the company name."""
    assert not _is_plausible_own_site(
        "La Cocina de Irma", "Chicago's Best Tacos - El Ranchito Grill", ""
    )


def test_is_plausible_own_site_rejects_empty_name():
    assert not _is_plausible_own_site("", "Anything", "Anything")


def test_is_excluded_domain_matches_bare_domain():
    assert _is_excluded_domain("facebook.com")


def test_is_excluded_domain_matches_any_subdomain():
    """Real bug caught during this phase's own validation: a real Brave
    Search hit for "La Cocina de Irma" (a business with no website field
    anywhere in Overpass/Apify) came back as
    `lacocinadeirma.restaurants-us.com` -- a per-business subdomain of an
    excluded directory network. No two businesses share the same subdomain,
    so an exact `host in _EXCLUDED_DOMAINS` check would silently miss this
    entire class of aggregator (see _is_excluded_domain's docstring)."""
    assert _is_excluded_domain("lacocinadeirma.restaurants-us.com")
    assert _is_excluded_domain("m.facebook.com")


def test_is_excluded_domain_does_not_match_unrelated_domain():
    assert not _is_excluded_domain("lacocinadeirma.com")
    # Real domain must not falsely match by simple substring -- a genuine
    # business domain that merely *contains* an excluded domain's name
    # (not as a real subdomain relationship) is never a false positive.
    assert not _is_excluded_domain("notfacebook.com")
