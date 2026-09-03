from app.modules.messages.ai_writer import build_ai_request


def test_build_ai_request_includes_known_fields():
    request = build_ai_request(
        company_name="Padaria Teste",
        segment="restaurants",
        city="Sorocaba",
        problem="No website found.",
        potential_solution="Criar um site institucional.",
        reasons=["No digital presence found.", "No phone number found."],
    )
    assert "Padaria Teste" in request.user_prompt
    assert "restaurants" in request.user_prompt
    assert "Sorocaba" in request.user_prompt
    assert "No website found." in request.user_prompt
    assert "Criar um site institucional." in request.user_prompt
    assert "No digital presence found." in request.user_prompt
    assert request.task == "message_generation"
    assert request.model == "claude-sonnet-5"


def test_build_ai_request_marks_missing_fields_as_unknown_not_blank():
    request = build_ai_request(
        company_name="Empresa Sem Dados",
        segment="clinics",
        city="Sorocaba",
        problem=None,
        potential_solution=None,
        reasons=[],
    )
    assert "UNKNOWN" in request.user_prompt
    assert "No additional supporting reasons" in request.user_prompt
