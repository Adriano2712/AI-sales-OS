from app.modules.business_analysis.scoring import (
    compute_activity_score,
    compute_deterministic_scores,
    compute_digital_maturity_score,
    compute_need_score,
    compute_overall_score,
)


def test_digital_maturity_zero_when_no_website():
    """No website is itself a measured fact, not an unknown."""
    assert compute_digital_maturity_score(has_website=False, website_digital_score=None) == 0.0


def test_digital_maturity_none_when_website_not_analyzed_yet():
    assert (
        compute_digital_maturity_score(has_website=True, website_digital_score=None) is None
    )


def test_digital_maturity_mirrors_website_digital_score():
    assert compute_digital_maturity_score(has_website=True, website_digital_score=72.5) == 72.5


def test_activity_score_all_signals_present():
    assert compute_activity_score(has_phone=True, has_website=True, has_opening_hours_evidence=True) == 100.0


def test_activity_score_no_signals():
    assert (
        compute_activity_score(has_phone=False, has_website=False, has_opening_hours_evidence=False)
        == 0.0
    )


def test_activity_score_partial_signals():
    assert compute_activity_score(has_phone=True, has_website=False, has_opening_hours_evidence=False) == round(
        100 / 3, 1
    )


def test_need_score_is_none_when_digital_maturity_unknown():
    assert compute_need_score(None) is None


def test_need_score_is_inverse_of_digital_maturity():
    assert compute_need_score(30.0) == 70.0
    assert compute_need_score(0.0) == 100.0
    assert compute_need_score(100.0) == 0.0


def test_deterministic_scores_no_website_case():
    scores = compute_deterministic_scores(
        has_website=False,
        website_digital_score=None,
        has_phone=True,
        has_opening_hours_evidence=False,
    )
    assert scores.digital_maturity_score == 0.0
    assert scores.need_score == 100.0
    assert scores.activity_score == round(100 / 3, 1)


def test_overall_score_renormalizes_over_evaluated_dimensions():
    # Only business_fit and activity evaluated, both 100 -> overall is 100.
    score = compute_overall_score(
        business_fit_score=100.0,
        activity_score=100.0,
        digital_maturity_score=None,
        need_score=None,
        compatibility_score=None,
    )
    assert score == 100.0


def test_overall_score_none_when_nothing_evaluated():
    assert (
        compute_overall_score(
            business_fit_score=None,
            activity_score=None,
            digital_maturity_score=None,
            need_score=None,
            compatibility_score=None,
        )
        is None
    )


def test_overall_score_weights_all_five_dimensions_when_all_known():
    score = compute_overall_score(
        business_fit_score=100.0,
        activity_score=100.0,
        digital_maturity_score=100.0,
        need_score=100.0,
        compatibility_score=100.0,
    )
    assert score == 100.0

    score_half = compute_overall_score(
        business_fit_score=0.0,
        activity_score=0.0,
        digital_maturity_score=0.0,
        need_score=0.0,
        compatibility_score=0.0,
    )
    assert score_half == 0.0
