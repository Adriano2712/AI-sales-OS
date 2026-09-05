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
    guard the fix itself, not just the user_prompt's data. Checked via the
    real request the function builds, in both languages, not the template
    string directly — that's what actually reaches the model."""
    for language in ("pt-BR", "en"):
        request = build_ai_request(
            company_name="Clínica Teste",
            segment="clinics",
            city="Natal",
            problem=None,
            potential_solution=None,
            reasons=[],
            language=language,
        )
        prompt = request.system_prompt.lower()
        assert "daqui do" in prompt or "daqui de" in prompt
        assert "never claim or imply" in prompt


def test_build_ai_request_defaults_to_portuguese():
    request = build_ai_request(
        company_name="Padaria Teste",
        segment="restaurants",
        city="Sorocaba",
        problem=None,
        potential_solution=None,
        reasons=[],
    )
    assert "brazilian portuguese" in request.system_prompt.lower()


def test_build_ai_request_writes_in_english_when_requested():
    """Real use case: a US company (Texas restaurants) shouldn't get a
    Portuguese message just because that's this system's historical
    default."""
    request = build_ai_request(
        company_name="Tex-Mex Grill",
        segment="restaurants",
        city="Austin",
        problem=None,
        potential_solution=None,
        reasons=[],
        language="en",
    )
    assert "natural, professional english" in request.system_prompt.lower()
    assert "brazilian portuguese" not in request.system_prompt.lower()


def test_default_language_for_country():
    from app.modules.messages.ai_writer import default_language_for_country

    assert default_language_for_country("BR") == "pt-BR"
    assert default_language_for_country("US") == "en"
    assert default_language_for_country("PT") == "en"  # only BR gets Portuguese by default
