from app.modules.website_analysis.enums import PageType
from app.modules.website_analysis.scoring import (
    compute_digital_score,
    compute_sub_scores,
    derive_problems,
)
from app.modules.website_analysis.signal_extraction import PageSignals


def _homepage(**overrides) -> PageSignals:
    defaults = dict(
        url="https://example.com/",
        page_type=PageType.HOMEPAGE,
        http_status=200,
        title="Example",
        meta_description="A description",
        has_viewport_meta=True,
        has_contact_form=True,
        has_phone_link=True,
        has_email_link=False,
        has_whatsapp_link=False,
        has_nav=True,
        has_custom_stylesheet=True,
        word_count=200,
    )
    defaults.update(overrides)
    return PageSignals(**defaults)


def test_no_pages_yields_all_none():
    scores = compute_sub_scores([])
    assert scores.funcionamento is None
    assert scores.mobile is None
    assert compute_digital_score(scores) is None


def test_unreachable_homepage_only_funcionamento_is_evaluable():
    pages = [
        PageSignals(url="https://example.com/", page_type=PageType.HOMEPAGE, http_status=None)
    ]
    scores = compute_sub_scores(pages)
    assert scores.funcionamento == 0.0
    assert scores.mobile is None
    assert scores.ux is None
    assert scores.conversao is None
    assert scores.conteudo is None
    assert scores.design is None
    # Only funcionamento evaluated -> digital_score equals it exactly
    # (weights renormalized over a single dimension).
    assert compute_digital_score(scores) == 0.0


def test_fully_healthy_site_scores_well_on_every_evaluable_dimension():
    pages = [_homepage()]
    scores = compute_sub_scores(pages)
    assert scores.funcionamento == 100.0
    assert scores.mobile == 100.0
    assert scores.conversao == 40.0  # 2 of 5 signals true (form, phone — no email/whatsapp/contact page)
    assert scores.conteudo == 75.0  # title, meta, word_count>=100 true; no SERVICES page
    assert scores.design == 100.0

    digital_score = compute_digital_score(scores)
    assert digital_score is not None
    assert 0 <= digital_score <= 100


def test_no_viewport_meta_scores_mobile_zero_not_unknown():
    pages = [_homepage(has_viewport_meta=False)]
    scores = compute_sub_scores(pages)
    assert scores.mobile == 0.0  # a real negative signal, not UNKNOWN


def test_no_stylesheet_link_leaves_design_unknown_not_zero():
    """spec section 35: absence of a signal we can't reliably interpret stays
    UNKNOWN — it must not be scored as bad design."""
    pages = [_homepage(has_custom_stylesheet=False)]
    scores = compute_sub_scores(pages)
    assert scores.design is None


def test_broken_subpage_lowers_funcionamento_and_ux():
    pages = [
        _homepage(),
        PageSignals(
            url="https://example.com/contato",
            page_type=PageType.CONTACT,
            http_status=404,
        ),
    ]
    scores = compute_sub_scores(pages)
    assert scores.funcionamento == 50.0  # 1 of 2 pages ok
    assert scores.ux is not None
    assert scores.ux < 100.0


def test_contact_page_present_boosts_conversao():
    pages = [
        _homepage(has_phone_link=False, has_contact_form=False, has_email_link=False, has_whatsapp_link=False),
        PageSignals(url="https://example.com/contato", page_type=PageType.CONTACT, http_status=200),
    ]
    scores = compute_sub_scores(pages)
    # Only the "reached a CONTACT page" signal is true among the 5.
    assert scores.conversao == 20.0


def test_services_page_present_boosts_conteudo():
    pages = [
        _homepage(title=None, meta_description=None, word_count=10),
        PageSignals(url="https://example.com/cardapio", page_type=PageType.SERVICES, http_status=200),
    ]
    scores = compute_sub_scores(pages)
    # Only the "reached a SERVICES page" signal is true among the 4.
    assert scores.conteudo == 25.0


def test_digital_score_renormalizes_weights_over_evaluated_dimensions_only():
    from app.modules.website_analysis.scoring import SubScores

    # Only two dimensions evaluated, both at 100 -> overall must be 100,
    # not degraded by the missing ones' weight.
    scores = SubScores(
        funcionamento=100.0, mobile=100.0, ux=None, conversao=None, conteudo=None, design=None
    )
    assert compute_digital_score(scores) == 100.0


def test_digital_score_is_none_when_nothing_is_evaluable():
    from app.modules.website_analysis.scoring import SubScores

    scores = SubScores(None, None, None, None, None, None)
    assert compute_digital_score(scores) is None


def test_derive_problems_no_pages_reports_inaccessible():
    problems = derive_problems([])
    assert len(problems) == 1
    assert "não pôde ser acessado" in problems[0]


def test_derive_problems_unreachable_homepage_reports_only_that():
    pages = [
        PageSignals(url="https://example.com/", page_type=PageType.HOMEPAGE, http_status=500)
    ]
    problems = derive_problems(pages)
    assert len(problems) == 1
    assert "HTTP 500" in problems[0]


def test_derive_problems_unreachable_homepage_with_no_status_still_reports_one_problem():
    pages = [
        PageSignals(url="https://example.com/", page_type=PageType.HOMEPAGE, http_status=None)
    ]
    problems = derive_problems(pages)
    assert len(problems) == 1
    assert "fora do ar" in problems[0]


def test_derive_problems_healthy_site_with_services_page_has_no_problems():
    pages = [
        _homepage(),
        PageSignals(url="https://example.com/servicos", page_type=PageType.SERVICES, http_status=200),
    ]
    assert derive_problems(pages) == []


def test_derive_problems_flags_missing_viewport():
    pages = [
        _homepage(has_viewport_meta=False),
        PageSignals(url="https://example.com/servicos", page_type=PageType.SERVICES, http_status=200),
    ]
    problems = derive_problems(pages)
    assert any("celular" in p for p in problems)


def test_derive_problems_flags_no_contact_method():
    pages = [
        _homepage(has_contact_form=False, has_phone_link=False, has_email_link=False, has_whatsapp_link=False),
        PageSignals(url="https://example.com/servicos", page_type=PageType.SERVICES, http_status=200),
    ]
    problems = derive_problems(pages)
    assert any("contato" in p for p in problems)


def test_derive_problems_contact_page_alone_counts_as_a_contact_method():
    pages = [
        _homepage(has_contact_form=False, has_phone_link=False, has_email_link=False, has_whatsapp_link=False),
        PageSignals(url="https://example.com/contato", page_type=PageType.CONTACT, http_status=200),
        PageSignals(url="https://example.com/servicos", page_type=PageType.SERVICES, http_status=200),
    ]
    problems = derive_problems(pages)
    assert not any("contato" in p for p in problems)


def test_derive_problems_flags_missing_nav():
    pages = [
        _homepage(has_nav=False),
        PageSignals(url="https://example.com/servicos", page_type=PageType.SERVICES, http_status=200),
    ]
    problems = derive_problems(pages)
    assert any("navegação" in p for p in problems)


def test_derive_problems_flags_no_services_page():
    pages = [_homepage()]
    problems = derive_problems(pages)
    assert any("serviços" in p for p in problems)


def test_derive_problems_flags_missing_title_or_description():
    pages = [
        _homepage(title=None),
        PageSignals(url="https://example.com/servicos", page_type=PageType.SERVICES, http_status=200),
    ]
    problems = derive_problems(pages)
    assert any("SEO" in p for p in problems)


def test_derive_problems_flags_thin_content():
    pages = [
        _homepage(word_count=10),
        PageSignals(url="https://example.com/servicos", page_type=PageType.SERVICES, http_status=200),
    ]
    problems = derive_problems(pages)
    assert any("raso" in p for p in problems)
