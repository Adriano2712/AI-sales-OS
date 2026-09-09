from app.modules.enrichment.website_search import _is_plausible_own_site


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
