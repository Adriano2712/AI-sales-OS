from app.modules.website_analysis.enums import PageFetchOutcome, PageType, WebsiteStatus
from app.modules.website_analysis.scoring import SubScores, compute_digital_score, compute_sub_scores
from app.modules.website_analysis.signal_extraction import PageSignals
from app.modules.website_analysis.status import CONFIDENT_QUALITY_STATUSES, derive_website_status

_ALL_NONE = SubScores(None, None, None, None, None, None)


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
        has_email_link=True,
        has_whatsapp_link=True,
        has_nav=True,
        has_custom_stylesheet=True,
        word_count=200,
    )
    defaults.update(overrides)
    return PageSignals(**defaults)


def test_no_pages_is_unknown():
    assert derive_website_status([], _ALL_NONE, None) == WebsiteStatus.UNKNOWN


def test_timeout_fetch_outcome_maps_to_timeout_status():
    pages = [_homepage(http_status=None, fetch_outcome=PageFetchOutcome.TIMEOUT)]
    assert derive_website_status(pages, _ALL_NONE, None) == WebsiteStatus.TIMEOUT


def test_dns_failure_fetch_outcome_maps_to_website_not_found():
    pages = [_homepage(http_status=None, fetch_outcome=PageFetchOutcome.DNS_FAILURE)]
    assert derive_website_status(pages, _ALL_NONE, None) == WebsiteStatus.WEBSITE_NOT_FOUND


def test_blocked_fetch_outcome_maps_to_blocked_status_never_poor():
    """The absolute rule, directly: a 403/anti-bot block is never POOR,
    regardless of what (if anything) could be scored."""
    pages = [_homepage(http_status=403, fetch_outcome=PageFetchOutcome.BLOCKED)]
    assert derive_website_status(pages, _ALL_NONE, None) == WebsiteStatus.BLOCKED


def test_connection_error_fetch_outcome_maps_to_offline():
    pages = [_homepage(http_status=None, fetch_outcome=PageFetchOutcome.CONNECTION_ERROR)]
    assert derive_website_status(pages, _ALL_NONE, None) == WebsiteStatus.OFFLINE


def test_definitive_http_error_with_no_special_outcome_maps_to_offline():
    pages = [_homepage(http_status=500)]
    assert derive_website_status(pages, _ALL_NONE, None) == WebsiteStatus.OFFLINE


def test_js_rendered_homepage_maps_to_js_required_never_poor():
    pages = [_homepage(word_count=2, looks_js_rendered=True)]
    # Even if some dimension happened to compute a low score, JS_REQUIRED
    # wins — never a quality judgment on a page we couldn't really see.
    low_scores = SubScores(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    assert derive_website_status(pages, low_scores, 0.0) == WebsiteStatus.JS_REQUIRED


def test_no_quality_score_and_no_special_outcome_is_unknown():
    pages = [_homepage()]
    assert derive_website_status(pages, _ALL_NONE, None) == WebsiteStatus.UNKNOWN


def test_few_evaluable_dimensions_is_analyzed_not_a_confident_tier():
    pages = [_homepage()]
    scores = SubScores(funcionamento=100.0, mobile=100.0, ux=None, conversao=None, conteudo=None, design=None)
    score = compute_digital_score(scores)
    assert derive_website_status(pages, scores, score) == WebsiteStatus.ANALYZED


def test_confidently_high_score_is_good():
    pages = [_homepage()]
    scores = compute_sub_scores(pages)
    score = compute_digital_score(scores)
    assert score is not None and score >= 70
    assert derive_website_status(pages, scores, score) == WebsiteStatus.GOOD


def test_confidently_mid_score_is_needs_improvement():
    pages = [_homepage(has_viewport_meta=False, has_custom_stylesheet=False, word_count=50)]
    scores = compute_sub_scores(pages)
    score = compute_digital_score(scores)
    assert score is not None and 40 <= score < 70
    assert derive_website_status(pages, scores, score) == WebsiteStatus.NEEDS_IMPROVEMENT


def test_confidently_low_score_is_poor():
    pages = [
        _homepage(
            has_viewport_meta=False,
            has_contact_form=False,
            has_phone_link=False,
            has_email_link=False,
            has_whatsapp_link=False,
            has_nav=False,
            has_custom_stylesheet=False,
            title=None,
            meta_description=None,
            word_count=5,
        )
    ]
    scores = compute_sub_scores(pages)
    score = compute_digital_score(scores)
    assert score is not None and score < 40
    assert derive_website_status(pages, scores, score) == WebsiteStatus.POOR


def test_js_required_is_not_in_confident_quality_statuses():
    """Regression guard for a real bug this phase's own end-to-end
    validation caught: compute_sub_scores can still mechanically produce a
    real-looking low score from a JS-only shell's near-empty HTML even
    though JS_REQUIRED means "we didn't really see the site" — service.py
    relies on this set to null that score back out. If JS_REQUIRED (or
    BLOCKED/TIMEOUT/WEBSITE_NOT_FOUND/OFFLINE/UNKNOWN) ever ends up in this
    set, that score would leak out again."""
    assert WebsiteStatus.JS_REQUIRED not in CONFIDENT_QUALITY_STATUSES
    assert WebsiteStatus.BLOCKED not in CONFIDENT_QUALITY_STATUSES
    assert WebsiteStatus.TIMEOUT not in CONFIDENT_QUALITY_STATUSES
    assert WebsiteStatus.WEBSITE_NOT_FOUND not in CONFIDENT_QUALITY_STATUSES
    assert WebsiteStatus.OFFLINE not in CONFIDENT_QUALITY_STATUSES
    assert WebsiteStatus.UNKNOWN not in CONFIDENT_QUALITY_STATUSES
    assert CONFIDENT_QUALITY_STATUSES == {
        WebsiteStatus.GOOD,
        WebsiteStatus.NEEDS_IMPROVEMENT,
        WebsiteStatus.POOR,
        WebsiteStatus.ANALYZED,
    }
