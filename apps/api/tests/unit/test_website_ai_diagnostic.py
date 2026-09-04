from app.modules.website_analysis.ai_diagnostic import SiteDiagnosticAIOutput, build_ai_request


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


def test_output_schema_accepts_a_real_compliant_paragraph_length():
    """Regression test: a real production run (5 clínicas em Salvador/BA,
    2026-09-04) failed the whole website_analysis job because a genuinely
    compliant 3-5 sentence Portuguese paragraph landed just over the
    original 800-char bound — a valid AI response got rejected by an
    over-tight safety net, not a bad one caught by a correct one."""
    paragraph = (
        "Sua clínica tem uma pontuação digital razoável, mas o site não tem uma página de "
        "serviços dedicada, o que significa que quem chega até ele buscando saber quais "
        "procedimentos, especialidades ou tratamentos são oferecidos não encontra essa "
        "informação de forma clara e objetiva no primeiro contato com a página. Isso é "
        "especialmente relevante porque pacientes em potencial costumam pesquisar antes de "
        "escolher onde marcar uma consulta, comparando o que cada clínica oferece, e a "
        "ausência dessa informação reduz a confiança e pode levá-los a procurar um "
        "concorrente que apresente esses dados de forma mais transparente. Criar uma página "
        "listando claramente os serviços disponíveis ajudaria o visitante a confirmar mais "
        "rápido que encontrou o lugar certo, reduzindo a perda desse contato antes mesmo de "
        "ele ligar ou agendar um atendimento pelo site."
    )
    assert len(paragraph) > 800
    output = SiteDiagnosticAIOutput(business_impact=paragraph)
    assert output.business_impact == paragraph
