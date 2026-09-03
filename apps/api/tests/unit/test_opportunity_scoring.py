from app.modules.opportunities.enums import OpportunityClassification, OpportunityStatus, OpportunityType
from app.modules.opportunities.scoring import (
    classify_opportunity,
    compute_components,
    compute_need,
    compute_opportunity_score,
    derive_next_action,
    derive_potential_solution,
    determine_opportunity_type,
)


def test_compute_need_averages_need_score_and_inverted_activity():
    assert compute_need(need_score=80.0, activity_score=40.0) == 70.0  # (80 + 60) / 2


def test_compute_need_falls_back_to_need_score_when_activity_unknown():
    assert compute_need(need_score=80.0, activity_score=None) == 80.0


def test_compute_need_falls_back_to_inverted_activity_when_need_score_unknown():
    assert compute_need(need_score=None, activity_score=40.0) == 60.0


def test_compute_need_none_when_both_unknown():
    assert compute_need(need_score=None, activity_score=None) is None


def test_compute_components_maps_digital_gap_to_need_score_directly():
    components = compute_components(business_fit_score=70.0, activity_score=100.0, need_score=90.0)
    assert components.digital_gap == 90.0
    assert components.business_fit == 70.0
    assert components.commercial_signals == 100.0
    assert components.need == 45.0  # (90 + (100 - 100)) / 2


def test_compute_opportunity_score_renormalizes_over_known_components():
    from app.modules.opportunities.scoring import OpportunityComponents

    # Only two of four known, both 100 -> overall 100.
    components = OpportunityComponents(
        digital_gap=100.0, business_fit=100.0, need=None, commercial_signals=None
    )
    assert compute_opportunity_score(components) == 100.0


def test_compute_opportunity_score_none_when_nothing_known():
    from app.modules.opportunities.scoring import OpportunityComponents

    components = OpportunityComponents(
        digital_gap=None, business_fit=None, need=None, commercial_signals=None
    )
    assert compute_opportunity_score(components) is None


def test_compute_opportunity_score_all_four_known():
    from app.modules.opportunities.scoring import OpportunityComponents

    components = OpportunityComponents(
        digital_gap=80.0, business_fit=80.0, need=80.0, commercial_signals=80.0
    )
    assert compute_opportunity_score(components) == 80.0


def test_classify_opportunity_thresholds():
    assert classify_opportunity(95.0) == OpportunityClassification.HIGH
    assert classify_opportunity(90.0) == OpportunityClassification.HIGH
    assert classify_opportunity(80.0) == OpportunityClassification.GOOD
    assert classify_opportunity(75.0) == OpportunityClassification.GOOD
    assert classify_opportunity(65.0) == OpportunityClassification.REVIEW
    assert classify_opportunity(60.0) == OpportunityClassification.REVIEW
    assert classify_opportunity(59.9) == OpportunityClassification.LOW
    assert classify_opportunity(0.0) == OpportunityClassification.LOW


def test_classify_opportunity_none_when_score_unknown():
    assert classify_opportunity(None) is None


def test_determine_opportunity_type_website_when_digital_maturity_low():
    assert determine_opportunity_type(30.0) == OpportunityType.WEBSITE
    assert determine_opportunity_type(49.9) == OpportunityType.WEBSITE


def test_determine_opportunity_type_other_when_digital_maturity_ok_or_unknown():
    assert determine_opportunity_type(50.0) == OpportunityType.OTHER
    assert determine_opportunity_type(80.0) == OpportunityType.OTHER
    assert determine_opportunity_type(None) == OpportunityType.OTHER


def test_derive_potential_solution_only_fires_for_website_type():
    assert derive_potential_solution(OpportunityType.OTHER, has_website=False) is None


def test_derive_potential_solution_no_website_vs_existing_website():
    no_site = derive_potential_solution(OpportunityType.WEBSITE, has_website=False)
    has_site = derive_potential_solution(OpportunityType.WEBSITE, has_website=True)
    assert no_site is not None and "Criar" in no_site
    assert has_site is not None and "Modernizar" in has_site
    assert no_site != has_site


def test_derive_next_action_covers_every_status():
    for status in OpportunityStatus:
        action = derive_next_action(status)
        assert isinstance(action, str) and action != ""


def test_derive_next_action_distinguishes_actionable_from_terminal_statuses():
    assert derive_next_action(OpportunityStatus.OPEN) != derive_next_action(
        OpportunityStatus.REJECTED
    )
    assert derive_next_action(OpportunityStatus.REJECTED) != derive_next_action(
        OpportunityStatus.ARCHIVED
    )
