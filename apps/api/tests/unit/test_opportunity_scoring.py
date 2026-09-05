from app.modules.companies.enums import CompanyStatus
from app.modules.opportunities.enums import (
    OpportunityClassification,
    OpportunityOutcome,
    OpportunityStatus,
    OpportunityType,
)
from app.modules.opportunities.scoring import (
    DEFAULT_WEIGHTS_V2,
    OpportunityFactors,
    apply_penalty,
    classify_opportunity,
    compute_components,
    compute_need,
    compute_opportunity_confidence,
    compute_opportunity_factors,
    compute_opportunity_score,
    compute_opportunity_score_v2,
    compute_penalties,
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


# --- Fase 7: Opportunity Score 2.0 -----------------------------------------


def _all_known_factors(**overrides) -> OpportunityFactors:
    defaults = dict(
        digital_gap=80.0,
        business_fit=80.0,
        service_fit=80.0,
        need=80.0,
        commercial_signals=80.0,
        buying_potential=80.0,
        website_opportunity=80.0,
        customer_validation=80.0,
        evidence_signal_balance=80.0,
    )
    defaults.update(overrides)
    return OpportunityFactors(**defaults)


def test_compute_opportunity_factors_customer_validation_is_presence_only():
    """Same design decision Fase 4 already made for the underlying evidence
    (see enrichment/service.py's Google review evidence): presence of real
    review data is the signal, never the star rating's actual value — no
    defensible threshold exists for "good enough" here."""
    factors = compute_opportunity_factors(
        business_fit_score=None,
        activity_score=None,
        need_score=None,
        service_fit_score=None,
        buying_potential_score=None,
        website_opportunity_score=None,
        has_google_reviews=True,
        evidence_signal_balance=None,
    )
    assert factors.customer_validation == 100.0


def test_compute_opportunity_factors_customer_validation_none_when_no_reviews():
    factors = compute_opportunity_factors(
        business_fit_score=None,
        activity_score=None,
        need_score=None,
        service_fit_score=None,
        buying_potential_score=None,
        website_opportunity_score=None,
        has_google_reviews=False,
        evidence_signal_balance=None,
    )
    assert factors.customer_validation is None


def test_compute_opportunity_score_v2_all_known_equals_the_common_value():
    assert compute_opportunity_score_v2(_all_known_factors()) == 80.0


def test_compute_opportunity_score_v2_none_when_nothing_known():
    empty = OpportunityFactors(None, None, None, None, None, None, None, None, None)
    assert compute_opportunity_score_v2(empty) is None


def test_compute_opportunity_score_v2_renormalizes_over_known_factors():
    # Only business_fit known, at 100 -> overall must be exactly 100, not
    # diluted by the other eight factors' weight.
    factors = OpportunityFactors(
        digital_gap=None,
        business_fit=100.0,
        service_fit=None,
        need=None,
        commercial_signals=None,
        buying_potential=None,
        website_opportunity=None,
        customer_validation=None,
        evidence_signal_balance=None,
    )
    assert compute_opportunity_score_v2(factors) == 100.0


def test_compute_opportunity_score_v2_default_weights_sum_to_one():
    """Not a hard requirement (renormalization would handle any positive
    weights), but a real, checkable invariant of the calibration actually
    shipped — a silent typo here would skew every score without any test
    ever catching it otherwise."""
    assert round(sum(DEFAULT_WEIGHTS_V2.values()), 6) == 1.0


def test_compute_opportunity_score_v2_respects_campaign_override():
    """A campaign that cares only about business_fit (weight 1.0, every
    other factor's weight zeroed out) must score purely on that dimension,
    ignoring the other eight factors entirely — even though they're all
    known and would otherwise pull the average down."""
    factors = _all_known_factors(business_fit=100.0, need=0.0)
    overriding_weights = {name: 0.0 for name in DEFAULT_WEIGHTS_V2}
    overriding_weights["business_fit"] = 1.0
    assert compute_opportunity_score_v2(factors, overriding_weights) == 100.0


def test_compute_opportunity_score_v2_missing_override_keys_fall_back_to_defaults():
    """A campaign overriding only one weight must not silently zero out
    every other factor — omitted keys keep DEFAULT_WEIGHTS_V2's value."""
    factors = _all_known_factors()
    partial_override = {"business_fit": 0.5}
    # All factors equal (80.0) -> whatever the weights are, renormalized
    # average is still 80.0, proving the other 8 factors weren't dropped.
    assert compute_opportunity_score_v2(factors, partial_override) == 80.0


def test_compute_penalties_no_penalty_for_a_healthy_open_company():
    penalty = compute_penalties(
        company_status=CompanyStatus.DISCOVERED, do_not_contact=False, existing_outcome=None
    )
    assert penalty.points == 0.0
    assert penalty.reasons == []


def test_compute_penalties_invalid_company_status():
    penalty = compute_penalties(
        company_status=CompanyStatus.INVALID, do_not_contact=False, existing_outcome=None
    )
    assert penalty.points == 60.0
    assert len(penalty.reasons) == 1


def test_compute_penalties_duplicate_company_status():
    penalty = compute_penalties(
        company_status=CompanyStatus.DUPLICATE, do_not_contact=False, existing_outcome=None
    )
    assert penalty.points == 60.0


def test_compute_penalties_do_not_contact():
    penalty = compute_penalties(
        company_status=CompanyStatus.DISCOVERED, do_not_contact=True, existing_outcome=None
    )
    assert penalty.points == 30.0


def test_compute_penalties_already_has_outcome():
    penalty = compute_penalties(
        company_status=CompanyStatus.DISCOVERED,
        do_not_contact=False,
        existing_outcome=OpportunityOutcome.CONTACTED,
    )
    assert penalty.points == 20.0


def test_compute_penalties_stack():
    penalty = compute_penalties(
        company_status=CompanyStatus.INVALID,
        do_not_contact=True,
        existing_outcome=OpportunityOutcome.WON,
    )
    assert penalty.points == 60.0 + 30.0 + 20.0
    assert len(penalty.reasons) == 3


def test_apply_penalty_subtracts_and_clips_at_zero():
    assert apply_penalty(50.0, 20.0) == 30.0
    assert apply_penalty(10.0, 60.0) == 0.0  # never negative


def test_apply_penalty_none_score_stays_none():
    assert apply_penalty(None, 30.0) is None


def test_compute_opportunity_confidence_scales_by_data_completeness():
    # Only 1 of 9 factors known -> confidence is a small fraction of the
    # AI's own confidence, not the AI's confidence unchanged.
    factors = OpportunityFactors(
        digital_gap=None,
        business_fit=80.0,
        service_fit=None,
        need=None,
        commercial_signals=None,
        buying_potential=None,
        website_opportunity=None,
        customer_validation=None,
        evidence_signal_balance=None,
    )
    confidence = compute_opportunity_confidence(90.0, factors)
    assert confidence == round(90.0 * (1 / 9), 1)
    assert confidence < 90.0


def test_compute_opportunity_confidence_full_completeness_equals_ai_confidence():
    confidence = compute_opportunity_confidence(90.0, _all_known_factors())
    assert confidence == 90.0


def test_compute_opportunity_confidence_none_when_ai_confidence_unknown():
    assert compute_opportunity_confidence(None, _all_known_factors()) is None
