from app.modules.website_analysis.enums import PageType
from app.modules.website_analysis.signal_extraction import (
    classify_link,
    extract_links,
    extract_page_signals,
    prioritize_links,
)


def test_classify_link_contact():
    assert classify_link("/contato", "Fale Conosco") == PageType.CONTACT


def test_classify_link_scheduling():
    assert classify_link("/agendamento", "Agendar horário") == PageType.SCHEDULING


def test_classify_link_services_menu():
    assert classify_link("/cardapio", "Cardápio") == PageType.SERVICES


def test_classify_link_about():
    assert classify_link("/sobre", "Quem somos") == PageType.ABOUT


def test_classify_link_other_when_no_keyword_matches():
    assert classify_link("/blog/post-1", "Últimas notícias") == PageType.OTHER


def test_classify_link_is_accent_insensitive():
    assert classify_link("/contato", "Contáto") == PageType.CONTACT


_FULL_PAGE_HTML = """
<html>
<head>
  <title>Restaurante Teste</title>
  <meta name="description" content="O melhor restaurante da cidade">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="stylesheet" href="/style.css">
</head>
<body>
  <nav>menu</nav>
  <form action="/contact"></form>
  <a href="tel:+551533334444">Ligue</a>
  <a href="mailto:contato@example.com">Email</a>
  <a href="https://wa.me/5515999998888">WhatsApp</a>
  <p>Lorem ipsum dolor sit amet consectetur adipiscing elit</p>
</body>
</html>
"""


def test_extract_page_signals_full_page():
    signals = extract_page_signals(_FULL_PAGE_HTML, PageType.HOMEPAGE, 200)
    assert signals.title == "Restaurante Teste"
    assert signals.meta_description == "O melhor restaurante da cidade"
    assert signals.has_viewport_meta is True
    assert signals.has_contact_form is True
    assert signals.has_phone_link is True
    assert signals.has_email_link is True
    assert signals.has_whatsapp_link is True
    assert signals.has_nav is True
    assert signals.has_custom_stylesheet is True
    assert signals.word_count > 0


def test_extract_page_signals_empty_html_never_fabricates():
    signals = extract_page_signals("", PageType.HOMEPAGE, None)
    assert signals.title is None
    assert signals.meta_description is None
    assert signals.has_viewport_meta is False
    assert signals.has_contact_form is False


def test_extract_page_signals_minimal_page_has_no_false_positives():
    signals = extract_page_signals("<html><body><p>Hi</p></body></html>", PageType.HOMEPAGE, 200)
    assert signals.has_viewport_meta is False
    assert signals.has_contact_form is False
    assert signals.has_phone_link is False
    assert signals.title is None


_LINKS_HTML = """
<html><body>
<a href="/contato">Contato</a>
<a href="/sobre">Sobre</a>
<a href="https://external.com/other">External</a>
<a href="#section">Anchor</a>
<a href="mailto:a@b.com">Email</a>
<a href="/contato">Contato Duplicado</a>
</body></html>
"""


def test_extract_links_stays_on_domain_and_dedupes():
    links = extract_links(_LINKS_HTML, "https://example.com/", "example.com")
    urls = [link.url for link in links]
    assert "https://example.com/contato" in urls
    assert "https://example.com/sobre" in urls
    assert not any("external.com" in u for u in urls)
    assert len(urls) == len(set(urls))  # deduped


def test_extract_links_excludes_anchors_mailto_tel_javascript():
    html = """
    <a href="#top">Top</a>
    <a href="mailto:a@b.com">Mail</a>
    <a href="tel:123">Tel</a>
    <a href="javascript:void(0)">JS</a>
    <a href="/real-page">Real</a>
    """
    links = extract_links(html, "https://example.com/", "example.com")
    assert len(links) == 1
    assert links[0].url == "https://example.com/real-page"


def test_prioritize_links_puts_contact_first():
    links = extract_links(_LINKS_HTML, "https://example.com/", "example.com")
    prioritized = prioritize_links(links, limit=10)
    assert prioritized[0][1] == PageType.CONTACT


def test_prioritize_links_respects_limit():
    links = extract_links(_LINKS_HTML, "https://example.com/", "example.com")
    prioritized = prioritize_links(links, limit=1)
    assert len(prioritized) == 1
