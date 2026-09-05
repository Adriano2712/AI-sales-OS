import socket
from urllib.parse import urlparse

import httpx

from app.modules.website_analysis.enums import PageFetchOutcome, PageType
from app.modules.website_analysis.signal_extraction import (
    PageSignals,
    extract_links,
    extract_page_signals,
    prioritize_links,
)

# Same courtesy as the Overpass provider (spec section 31: respect the rules
# applicable to sites) — identify the client rather than sending a generic
# HTTP-library default.
_USER_AGENT = "ai-sales-os-website-analysis/0.1 (internal tool)"

# Fase 5: real, well-known anti-bot/WAF status codes — 403 (forbidden,
# overwhelmingly a WAF/bot-protection response for a benign crawler in
# practice) and 429 (rate-limited, definitionally a protective mechanism,
# never a "bad website" signal). 503 is only treated as a block when a
# concrete challenge marker is also found (see _classify_response) — on its
# own it's just as likely to be genuine maintenance.
_ANTI_BOT_STATUS_CODES = (403, 429)
_BOT_CHALLENGE_MARKERS = (
    "checking your browser",
    "attention required",
    "just a moment",
    "cf-browser-verification",
    "captcha",
)


def _classify_response(response: httpx.Response) -> PageFetchOutcome:
    """Real, inspectable evidence only — a known anti-bot status code, or a
    challenge marker actually present in the response body/headers. Never a
    guess from the mere fact that a page returned an error."""
    if response.status_code in _ANTI_BOT_STATUS_CODES:
        return PageFetchOutcome.BLOCKED
    if response.status_code == 503:
        server_header = response.headers.get("server", "").lower()
        body_sample = response.text[:2000].lower()
        if "cloudflare" in server_header or any(
            marker in body_sample for marker in _BOT_CHALLENGE_MARKERS
        ):
            return PageFetchOutcome.BLOCKED
    return PageFetchOutcome.RESPONDED


def _is_dns_failure(exc: BaseException) -> bool:
    """Walks the exception's __cause__ chain for a real socket.gaierror —
    the actual OS-level DNS resolution failure. Checking the exception
    *type* (stable across platforms) rather than matching on the message
    string (which differs by OS) — real evidence, not an invented signal."""
    current: BaseException | None = exc
    for _ in range(5):
        if isinstance(current, socket.gaierror):
            return True
        if current is None:
            return False
        current = current.__cause__
    return False


class WebsiteCrawler:
    """Limited crawler (spec section 31): homepage plus up to `max_pages - 1`
    same-domain pages, one link-hop deep by default, bounded by `timeout`
    per request. No JS execution, no CAPTCHA/anti-bot bypass, never leaves
    the site's own domain.
    """

    def __init__(
        self,
        max_pages: int = 5,
        max_depth: int = 1,
        timeout: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._max_pages = max_pages
        self._max_depth = max_depth
        self._timeout = timeout
        # Injectable so tests can point the crawler at an in-memory mock
        # transport instead of the real network (spec section 31 also means
        # automated tests must never hit a real third-party site). None (the
        # default) uses httpx's real network transport.
        self._transport = transport

    async def crawl(self, root_url: str) -> list[PageSignals]:
        normalized_root = root_url if "://" in root_url else f"https://{root_url}"
        parsed = urlparse(normalized_root)
        domain = parsed.netloc
        homepage_url = f"{parsed.scheme}://{domain}{parsed.path or '/'}"

        pages: list[PageSignals] = []
        visited: set[str] = {homepage_url}

        async with httpx.AsyncClient(
            timeout=self._timeout,
            follow_redirects=True,
            headers={"User-Agent": _USER_AGENT},
            transport=self._transport,
        ) as client:
            homepage_signals, homepage_html = await self._fetch(
                client, homepage_url, PageType.HOMEPAGE
            )
            pages.append(homepage_signals)

            homepage_ok = (
                homepage_signals.http_status is not None and homepage_signals.http_status < 400
            )
            if homepage_ok and self._max_depth >= 1:
                links = extract_links(homepage_html, homepage_url, domain)
                for link, page_type in prioritize_links(links, max(0, self._max_pages - 1)):
                    if len(pages) >= self._max_pages or link.url in visited:
                        continue
                    visited.add(link.url)
                    signals, _ = await self._fetch(client, link.url, page_type)
                    pages.append(signals)

        return pages

    async def _fetch(
        self, client: httpx.AsyncClient, url: str, page_type: PageType
    ) -> tuple[PageSignals, str]:
        try:
            response = await client.get(url)
        except httpx.TimeoutException as exc:
            return PageSignals(
                url=url,
                page_type=page_type,
                http_status=None,
                error=str(exc),
                fetch_outcome=PageFetchOutcome.TIMEOUT,
            ), ""
        except httpx.ConnectError as exc:
            outcome = (
                PageFetchOutcome.DNS_FAILURE
                if _is_dns_failure(exc)
                else PageFetchOutcome.CONNECTION_ERROR
            )
            return PageSignals(
                url=url, page_type=page_type, http_status=None, error=str(exc), fetch_outcome=outcome
            ), ""
        except httpx.HTTPError as exc:
            return PageSignals(
                url=url,
                page_type=page_type,
                http_status=None,
                error=str(exc),
                fetch_outcome=PageFetchOutcome.CONNECTION_ERROR,
            ), ""

        fetch_outcome = _classify_response(response)
        html = response.text if response.status_code < 400 else ""
        signals = extract_page_signals(html, page_type, response.status_code, fetch_outcome=fetch_outcome)
        signals.url = url
        return signals, html
