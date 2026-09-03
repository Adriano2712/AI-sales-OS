from urllib.parse import urlparse

import httpx

from app.modules.website_analysis.enums import PageType
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
        except httpx.HTTPError as exc:
            return PageSignals(url=url, page_type=page_type, http_status=None, error=str(exc)), ""

        html = response.text if response.status_code < 400 else ""
        signals = extract_page_signals(html, page_type, response.status_code)
        signals.url = url
        return signals, html
