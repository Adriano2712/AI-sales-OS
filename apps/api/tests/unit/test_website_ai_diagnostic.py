from app.modules.website_analysis.ai_diagnostic import build_ai_request


def test_build_ai_request_includes_known_fields():
    request = build_ai_request(
        company_name="Padaria Teste",
        segment="restaurants",
        digital_score=42.5,
        problems=["Site não é otimizado para celular."],
    )
    assert "Padaria Teste" in request.user_prompt
    assert "restaurants" in request.user_prompt
    assert "42.5" in request.user_prompt
    assert "Site não é otimizado para celular." in request.user_prompt
    assert request.task == "site_diagnostic"
    assert request.model == "claude-sonnet-5"


def test_build_ai_request_marks_missing_score_as_unknown_not_blank():
    request = build_ai_request(
        company_name="Empresa Sem Dados",
        segment="clinics",
        digital_score=None,
        problems=[],
    )
    assert "UNKNOWN" in request.user_prompt
    assert "No concrete problems were found" in request.user_prompt
