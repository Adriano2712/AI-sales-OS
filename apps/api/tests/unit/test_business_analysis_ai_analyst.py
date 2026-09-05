import pytest
from pydantic import ValidationError

from app.modules.business_analysis.ai_analyst import BusinessAnalysisAIOutput, build_ai_request


def _valid_output_kwargs(**overrides) -> dict:
    defaults = dict(
        business_fit_score=70,
        compatibility_score=60,
        service_fit_score=65,
        buying_potential_score=50,
        buying_potential_summary="Some signals suggest moderate digital investment potential.",
        confidence=55,
        findings=[],
        problems=[],
    )
    defaults.update(overrides)
    return defaults


def test_output_schema_accepts_hedged_buying_language():
    output = BusinessAnalysisAIOutput(**_valid_output_kwargs())
    assert output.buying_potential_score == 50


@pytest.mark.parametrize(
    "phrase",
    [
        "This business wants to buy a new website.",
        "The owner will buy an e-commerce platform soon.",
        "Esta empresa quer comprar um site novo.",
        "O dono decidiu comprar um sistema de agendamento.",
        "They are ready to buy immediately.",
    ],
)
def test_output_schema_rejects_assertive_buying_language(phrase):
    """The Fase 6 absolute rule, enforced in code (not just prompted): never
    an assertive claim about what a business has decided or wants — only
    hedged, signal-based language."""
    with pytest.raises(ValidationError):
        BusinessAnalysisAIOutput(**_valid_output_kwargs(buying_potential_summary=phrase))


def test_output_schema_accepts_signal_based_phrasing_containing_the_word_buy():
    """The validator targets specific assertive phrases, not the mere
    presence of the word "buy" — a hedged sentence that happens to use it
    responsibly must still pass."""
    output = BusinessAnalysisAIOutput(
        **_valid_output_kwargs(
            buying_potential_summary="Signals do not indicate any near-term buy-side activity."
        )
    )
    assert "buy" in output.buying_potential_summary.lower()


def test_build_ai_request_includes_campaign_services_when_provided():
    request = build_ai_request(
        company_name="Padaria Teste",
        segment="restaurants",
        city="Sorocaba",
        state="SP",
        digital_maturity_score=40.0,
        activity_score=60.0,
        need_score=60.0,
        website_findings=None,
        evidence_claims=[],
        services=["website", "e-commerce"],
    )
    assert "website, e-commerce" in request.user_prompt
    assert "Services being sold in this campaign" in request.user_prompt


def test_build_ai_request_falls_back_to_generic_services_when_none_given():
    request = build_ai_request(
        company_name="Padaria Teste",
        segment="restaurants",
        city="Sorocaba",
        state="SP",
        digital_maturity_score=40.0,
        activity_score=60.0,
        need_score=60.0,
        website_findings=None,
        evidence_claims=[],
        services=[],
    )
    assert "No specific services were defined for this campaign" in request.user_prompt
    assert "websites" in request.user_prompt


def test_build_ai_request_services_defaults_to_none_safely():
    """`services` is an optional parameter (existing callers that predate
    Fase 6 must not break) — omitting it entirely must behave exactly like
    passing an empty list."""
    request = build_ai_request(
        company_name="Padaria Teste",
        segment="restaurants",
        city="Sorocaba",
        state="SP",
        digital_maturity_score=None,
        activity_score=None,
        need_score=None,
        website_findings=None,
        evidence_claims=[],
    )
    assert "No specific services were defined for this campaign" in request.user_prompt
