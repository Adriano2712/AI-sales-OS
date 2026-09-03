import unicodedata
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from app.modules.website_analysis.enums import PageType


@dataclass
class LinkInfo:
    url: str
    text: str


@dataclass
class PageSignals:
    """Objective, directly-observable facts about one crawled page (spec
    section 30) — never a judgment call. Judgment (scoring) happens
    separately in scoring.py, over a list of these."""

    url: str
    page_type: PageType
    http_status: int | None
    title: str | None = None
    meta_description: str | None = None
    has_viewport_meta: bool = False
    has_contact_form: bool = False
    has_phone_link: bool = False
    has_email_link: bool = False
    has_whatsapp_link: bool = False
    has_nav: bool = False
    has_custom_stylesheet: bool = False
    word_count: int = 0
    error: str | None = None


def _as_str(value: str | list[str] | None) -> str:
    """BeautifulSoup types an attribute value as `str | list[str]` (multi-valued
    attributes like `class` are lists) even though `href`/`content` are always
    plain strings at runtime — narrows that back to a str we can call string
    methods on."""
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(value)
    return value


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


# Spec section 31's priority list (serviços, produtos, contato, sobre,
# agendamento, cardápio) collapsed into page types. Order matters in
# prioritize_links below, not here — this is just keyword -> type.
_PAGE_TYPE_KEYWORDS: dict[PageType, tuple[str, ...]] = {
    PageType.CONTACT: ("contato", "contact", "fale conosco"),
    PageType.SCHEDULING: ("agendar", "agendamento", "reserva", "marcar horario", "booking"),
    PageType.SERVICES: ("servico", "cardapio", "menu", "produto", "service"),
    PageType.ABOUT: ("sobre", "quem somos", "about"),
}


def classify_link(href: str, text: str) -> PageType:
    """Pure, keyword-based — no JS execution, just what's in the href/link
    text. Unit tested directly."""
    combined = _fold(f"{href} {text}")
    for page_type, keywords in _PAGE_TYPE_KEYWORDS.items():
        if any(keyword in combined for keyword in keywords):
            return page_type
    return PageType.OTHER


def extract_page_signals(html: str, page_type: PageType, http_status: int | None) -> PageSignals:
    """Pure — takes already-fetched HTML, no network. `url` is left blank;
    the caller (crawler) fills it in, since this function doesn't know the
    page's own address."""
    if not html:
        return PageSignals(url="", page_type=page_type, http_status=http_status)

    soup = BeautifulSoup(html, "html.parser")

    title = soup.title.get_text(strip=True) if soup.title else None

    meta_description_tag = soup.find("meta", attrs={"name": "description"})
    meta_description = None
    if meta_description_tag:
        content = _as_str(meta_description_tag.get("content")).strip()
        meta_description = content or None

    viewport_tag = soup.find("meta", attrs={"name": "viewport"})
    has_viewport_meta = bool(
        viewport_tag and "width=device-width" in _as_str(viewport_tag.get("content"))
    )

    links = soup.find_all("a", href=True)
    hrefs = [_as_str(a["href"]) for a in links]
    has_phone_link = any(href.startswith("tel:") for href in hrefs)
    has_email_link = any(href.startswith("mailto:") for href in hrefs)
    has_whatsapp_link = any("wa.me" in href or "whatsapp" in href.lower() for href in hrefs)

    return PageSignals(
        url="",
        page_type=page_type,
        http_status=http_status,
        title=title or None,
        meta_description=meta_description or None,
        has_viewport_meta=has_viewport_meta,
        has_contact_form=bool(soup.find("form")),
        has_phone_link=has_phone_link,
        has_email_link=has_email_link,
        has_whatsapp_link=has_whatsapp_link,
        has_nav=bool(soup.find("nav")),
        has_custom_stylesheet=bool(soup.find("link", attrs={"rel": "stylesheet"})),
        word_count=len(soup.get_text().split()),
    )


def extract_links(html: str, base_url: str, domain: str) -> list[LinkInfo]:
    """Pure — same-domain links only (the crawler never leaves the site being
    analyzed), fragments/mailto/tel/javascript excluded, deduplicated."""
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    results: list[LinkInfo] = []
    seen: set[str] = set()

    for a in soup.find_all("a", href=True):
        href = _as_str(a["href"]).strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue

        absolute = urljoin(base_url, href).split("#")[0]
        if urlparse(absolute).netloc != domain:
            continue
        if absolute in seen:
            continue

        seen.add(absolute)
        results.append(LinkInfo(url=absolute, text=a.get_text(strip=True)))

    return results


_PRIORITY_ORDER: dict[PageType, int] = {
    PageType.CONTACT: 0,
    PageType.SCHEDULING: 1,
    PageType.SERVICES: 2,
    PageType.ABOUT: 3,
    PageType.OTHER: 4,
}


def prioritize_links(links: list[LinkInfo], limit: int) -> list[tuple[LinkInfo, PageType]]:
    """Picks up to `limit` links, preferring spec section 31's priority page
    types over generic ones. Pure — sorting only, no I/O."""
    classified = [(link, classify_link(link.url, link.text)) for link in links]
    classified.sort(key=lambda pair: _PRIORITY_ORDER.get(pair[1], 99))
    return classified[:limit]
