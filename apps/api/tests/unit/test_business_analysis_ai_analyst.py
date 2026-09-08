import pytest
from pydantic import ValidationError

from app.modules.business_analysis.ai_analyst import (
    BusinessAnalysisAIOutput,
    _coerce_string_list,
    build_ai_request,
)


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


def test_output_schema_accepts_a_real_list_unchanged():
    output = BusinessAnalysisAIOutput(
        **_valid_output_kwargs(findings=["Real finding one.", "Real finding two."])
    )
    assert output.findings == ["Real finding one.", "Real finding two."]


def test_output_schema_recovers_item_tagged_string_output():
    """Real failure caught running the Denver campaign (Fase 13/14): under
    forced tool-use, Claude sometimes returns `findings`/`problems` as a
    single string of <item> tags instead of a real JSON array. Must recover
    the real content, not just reject the whole analysis."""
    malformed = "\n<item>Website status is UNKNOWN.</item>\n<item>No reviews found.</item>\n</problems>\n"
    output = BusinessAnalysisAIOutput(**_valid_output_kwargs(problems=malformed))
    assert output.problems == ["Website status is UNKNOWN.", "No reviews found."]


def test_output_schema_recovers_bare_unknown_tag_as_single_entry():
    """Real second failure shape from the same validation: no <item>
    wrapping at all, just a bare tag with no real content -- the tag itself
    carries no information worth keeping, so this becomes an empty list
    rather than a fabricated single entry."""
    output = BusinessAnalysisAIOutput(**_valid_output_kwargs(findings="\n<UNKNOWN>\n"))
    assert output.findings == []


def test_output_schema_recovers_string_with_leaked_tool_call_tags():
    """Real third failure shape: a stray `</invoke>` tag leaking from the
    tool-call format itself, mixed in with real <item> content."""
    malformed = "\n<item>Digital presence is minimal.</item>\n</problems>\n</invoke>\n"
    output = BusinessAnalysisAIOutput(**_valid_output_kwargs(problems=malformed))
    assert output.problems == ["Digital presence is minimal."]


def test_coerce_string_list_leaves_real_lists_unchanged():
    assert _coerce_string_list(["a", "b"]) == ["a", "b"]


def test_coerce_string_list_strips_tags_from_untagged_string():
    """A plain sentence with no <item> wrapping at all still carries real
    content -- kept as a single-item list, not discarded."""
    assert _coerce_string_list("Insufficient public evidence to assess X.") == [
        "Insufficient public evidence to assess X."
    ]


def test_output_schema_defaults_missing_problems_to_empty_list():
    """Real second failure shape from the same Denver validation ("La Calle
    Grill"): the model's tool-call input dropped the `problems` key
    entirely, alongside a malformed `findings` string -- Pydantic's
    "Field required" error would otherwise discard a real analysis over one
    omitted field. Empty list is the honest default (asserts nothing),
    never a fabricated problem."""
    kwargs = _valid_output_kwargs()
    del kwargs["problems"]
    output = BusinessAnalysisAIOutput(**kwargs)
    assert output.problems == []


def test_output_schema_truncates_item_tagged_string_over_the_length_cap():
    """Real second failure shape, other half: the same malformed response's
    recovered `findings` held 12 real <item> entries -- over max_length=8.
    Truncating keeps the real, first-produced content instead of rejecting
    the whole analysis over a length the model exceeded."""
    malformed = "".join(f"<item>Finding number {i}.</item>" for i in range(12))
    output = BusinessAnalysisAIOutput(**_valid_output_kwargs(findings=malformed))
    assert len(output.findings) == 8
    assert output.findings[0] == "Finding number 0."


def test_coerce_string_list_truncates_a_real_overlong_list():
    long_list = [f"item {i}" for i in range(12)]
    assert _coerce_string_list(long_list) == long_list[:8]


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
