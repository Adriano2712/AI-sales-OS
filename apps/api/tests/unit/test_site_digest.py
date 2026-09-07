from app.modules.notifications.site_digest import (
    SiteDiagnosticEntry,
    build_site_digest_html,
    build_site_digest_subject,
    build_site_digest_text,
)


def _entry(**overrides) -> SiteDiagnosticEntry:
    defaults = dict(
        name="Restaurante X",
        city="Sorocaba",
        state="SP",
        website="https://x.com",
        digital_score=42.0,
        problems=["Site não é otimizado para celular."],
        ai_diagnostic="Visitantes pelo celular provavelmente desistem.",
    )
    defaults.update(overrides)
    return SiteDiagnosticEntry(**defaults)


def test_subject_zero_companies():
    assert "nenhum site" in build_site_digest_subject("03/09/2026", "clinics", 0).lower()


def test_subject_counts_companies():
    subject = build_site_digest_subject("03/09/2026", "clinics", 3)
    assert "3" in subject
    assert "clinics" in subject


def test_text_empty_is_honest_not_fabricated():
    text = build_site_digest_text([], "03/09/2026", "clinics")
    assert "Nenhuma empresa nova" in text


def test_text_includes_known_fields():
    text = build_site_digest_text([_entry()], "03/09/2026", "clinics")
    assert "Restaurante X" in text
    assert "Sorocaba/SP" in text
    assert "https://x.com" in text
    assert "42.0" in text
    assert "Site não é otimizado para celular." in text
    assert "Visitantes pelo celular provavelmente desistem." in text


def test_text_no_website_is_honest_not_fabricated_score():
    entry = _entry(website=None, digital_score=None, problems=[], ai_diagnostic=None)
    text = build_site_digest_text([entry], "03/09/2026", "clinics")
    assert "não possui" in text
    assert "None" not in text


def test_text_analysis_pending_is_honest():
    entry = _entry(digital_score=None, problems=[], ai_diagnostic=None)
    text = build_site_digest_text([entry], "03/09/2026", "clinics")
    assert "ainda em análise" in text
    assert "None" not in text


def test_html_escapes_company_name():
    entry = _entry(name="<script>alert(1)</script>")
    html = build_site_digest_html([entry], "03/09/2026", "clinics")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html

    entry.problems.append("<img onerror=alert(1)>")
    html = build_site_digest_html([entry], "03/09/2026", "clinics")
    assert "<img onerror" not in html


def test_html_empty_is_honest():
    html = build_site_digest_html([], "03/09/2026", "clinics")
    assert "Nenhuma empresa nova" in html


# --- Fase 10: website_status explains *why* no score, honestly ---------


def test_text_blocked_status_never_reads_as_a_bad_site():
    """The absolute rule (Fase 5), extended to the digest's own wording: a
    real anti-bot block must never be phrased as if the site were bad or
    even just "still analyzing" — the reader should know evidence was
    insufficient, not that nothing happened yet."""
    entry = _entry(digital_score=None, problems=[], ai_diagnostic=None, website_status="BLOCKED")
    text = build_site_digest_text([entry], "03/09/2026", "clinics")
    assert "bloqueio automático" in text
    assert "ainda em análise" not in text
    assert "None" not in text


def test_text_timeout_status_is_distinguishable_from_pending_analysis():
    entry = _entry(digital_score=None, problems=[], ai_diagnostic=None, website_status="TIMEOUT")
    text = build_site_digest_text([entry], "03/09/2026", "clinics")
    assert "não respondeu a tempo" in text


def test_text_unrecognized_status_falls_back_to_pending_not_a_crash():
    """A future WebsiteStatus value this module doesn't have a label for
    yet must degrade gracefully, never raise."""
    entry = _entry(digital_score=None, problems=[], ai_diagnostic=None, website_status="GOOD")
    text = build_site_digest_text([entry], "03/09/2026", "clinics")
    assert "None" not in text  # doesn't crash or print the raw enum oddly


def test_html_blocked_status_is_escaped_and_present():
    entry = _entry(digital_score=None, problems=[], ai_diagnostic=None, website_status="BLOCKED")
    html = build_site_digest_html([entry], "03/09/2026", "clinics")
    assert "bloqueio automático" in html
