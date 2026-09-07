from app.modules.notifications.digest import (
    DigestCompanyEntry,
    DigestSummary,
    build_digest_html,
    build_digest_subject,
    build_digest_summary,
    build_digest_text,
)


def _entry(**overrides) -> DigestCompanyEntry:
    defaults = dict(
        name="Restaurante X",
        segment="restaurants",
        city="Sorocaba",
        state="SP",
        phone="15999999999",
        website="https://x.com",
        overall_score=62.7,
        classification="REVIEW",
    )
    defaults.update(overrides)
    return DigestCompanyEntry(**defaults)


def test_subject_zero_companies():
    assert "nenhuma empresa" in build_digest_subject("03/09/2026", "restaurants", 0).lower()


def test_subject_counts_companies():
    subject = build_digest_subject("03/09/2026", "restaurants", 3)
    assert "3" in subject
    assert "restaurants" in subject


def test_text_empty_is_honest_not_fabricated():
    text = build_digest_text([], "03/09/2026", "restaurants")
    assert "Nenhuma empresa nova" in text


def test_text_includes_known_fields():
    text = build_digest_text([_entry()], "03/09/2026", "restaurants")
    assert "Restaurante X" in text
    assert "Sorocaba/SP" in text
    assert "15999999999" in text
    assert "https://x.com" in text
    assert "62.7" in text
    assert "REVIEW" in text


def test_text_never_fabricates_missing_score():
    entry = _entry(overall_score=None, classification=None)
    text = build_digest_text([entry], "03/09/2026", "restaurants")
    assert "ainda em andamento" in text
    assert "None" not in text


def test_text_never_fabricates_missing_phone_or_website():
    entry = _entry(phone=None, website=None)
    text = build_digest_text([entry], "03/09/2026", "restaurants")
    assert "não informado" in text
    assert "None" not in text


def test_html_escapes_company_name():
    entry = _entry(name="<script>alert(1)</script>")
    html = build_digest_html([entry], "03/09/2026", "restaurants")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_html_empty_is_honest():
    html = build_digest_html([], "03/09/2026", "restaurants")
    assert "Nenhuma empresa nova" in html


# --- Fase 10: rich per-lead fields + summary counters -----------------


def test_text_includes_fase10_fields_when_present():
    entry = _entry(
        opportunity_score=77.7,
        opportunity_confidence=24.4,
        service_fit_score=65.0,
        buying_potential_summary="Alguns sinais sugerem potencial de investimento digital.",
        google_rating=4.8,
        google_review_count=512,
        instagram_url="https://instagram.com/restaurantex",
        reasons=["Sem site encontrado.", "Nenhum WhatsApp encontrado."],
    )
    text = build_digest_text([entry], "03/09/2026", "restaurants")
    assert "Oportunidade: 77.7 (confiança: 24.4)" in text
    assert "Fit de serviço: 65.0" in text
    assert "Google: 4.8 (512 avaliações)" in text
    assert "Instagram: https://instagram.com/restaurantex" in text
    assert "Alguns sinais sugerem potencial" in text
    assert "Sem site encontrado." in text


def test_text_omits_fase10_fields_when_absent_never_fabricates():
    """Every Fase 10 field defaults to None/empty — a company whose
    scoring hasn't reached that stage yet must not show a fabricated line
    for it (spec's absolute rule, extended to the digest)."""
    text = build_digest_text([_entry()], "03/09/2026", "restaurants")
    assert "Oportunidade:" not in text
    assert "Fit de serviço:" not in text
    assert "Google:" not in text
    assert "Instagram:" not in text
    assert "None" not in text


def test_html_includes_fase10_detail_row_when_present():
    entry = _entry(opportunity_score=90.0, google_rating=4.5, google_review_count=100)
    html = build_digest_html([entry], "03/09/2026", "restaurants")
    assert "Oportunidade: 90.0" in html
    assert "Google: 4.5 (100 avaliações)" in html


def test_html_escapes_instagram_and_reasons():
    entry = _entry(
        instagram_url="https://instagram.com/x?a=<script>",
        reasons=["<script>alert(1)</script>"],
    )
    html = build_digest_html([entry], "03/09/2026", "restaurants")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_build_digest_summary_tallies_classifications():
    entries = [
        _entry(classification="HIGH", opportunity_score=95.0),
        _entry(classification="HIGH", opportunity_score=91.0),
        _entry(classification="GOOD", opportunity_score=80.0),
        _entry(classification="LOW", opportunity_score=10.0),
        _entry(classification=None, opportunity_score=None),
    ]
    summary = build_digest_summary(entries)
    assert summary == DigestSummary(
        total=5, high=2, good=1, review=0, low=1, unscored=1, average_opportunity_score=69.0
    )


def test_build_digest_summary_empty_entries():
    summary = build_digest_summary([])
    assert summary.total == 0
    assert summary.average_opportunity_score is None


def test_build_digest_summary_never_fabricates_average_from_unscored_only():
    entries = [_entry(classification=None, opportunity_score=None)]
    summary = build_digest_summary(entries)
    assert summary.average_opportunity_score is None  # no real scores to average


def test_text_includes_summary_line_when_provided():
    entries = [_entry(classification="HIGH", opportunity_score=95.0)]
    summary = build_digest_summary(entries)
    text = build_digest_text(entries, "03/09/2026", "restaurants", summary=summary)
    assert "Resumo:" in text
    assert "1 HIGH" in text
    assert "95.0" in text


def test_text_without_summary_matches_original_behavior():
    """summary is optional — omitting it entirely must behave exactly like
    before Fase 10 (backward compatibility for any other caller)."""
    text_without = build_digest_text([_entry()], "03/09/2026", "restaurants")
    assert "Resumo:" not in text_without


def test_html_includes_summary_when_provided():
    entries = [_entry(classification="GOOD", opportunity_score=80.0)]
    summary = build_digest_summary(entries)
    html = build_digest_html(entries, "03/09/2026", "restaurants", summary=summary)
    assert "Resumo:" in html
    assert "1 GOOD" in html
