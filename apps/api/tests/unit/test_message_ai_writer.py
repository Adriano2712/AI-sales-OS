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


def test_build_ai_request_includes_real_sender_identity_when_given():
    """Real finding: without a real sender identity, the model would
    improvise a fabricated "daqui de [cidade do prospect]" line implying a
    local presence that doesn't exist."""
    request = build_ai_request(
        company_name="Clínica Teste",
        segment="clinics",
        city="Natal",
        problem="No website found.",
        potential_solution="Criar um site institucional.",
        reasons=[],
        sender_name="Flowa.ai",
        sender_location="Sorocaba-SP",
    )
    assert "Flowa.ai" in request.user_prompt
    assert "Sorocaba-SP" in request.user_prompt


def test_build_ai_request_sender_stays_unknown_when_not_configured():
    request = build_ai_request(
        company_name="Clínica Teste",
        segment="clinics",
        city="Natal",
        problem=None,
        potential_solution=None,
        reasons=[],
    )
    assert "UNKNOWN" in request.user_prompt
    assert "do not name a specific software house" in request.user_prompt


def test_system_prompt_forbids_claiming_local_presence():
    """The actual bug this fixes lived in the system prompt's ambiguity —
    guard the fix itself, not just the user_prompt's data."""
    from app.modules.messages.ai_writer import _SYSTEM_PROMPT

    assert "daqui do" in _SYSTEM_PROMPT.lower() or "daqui de" in _SYSTEM_PROMPT.lower()
    assert "never claim or imply" in _SYSTEM_PROMPT.lower()
