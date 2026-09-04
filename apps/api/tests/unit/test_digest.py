from app.modules.notifications.digest import (
    DigestCompanyEntry,
    build_digest_html,
    build_digest_subject,
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
