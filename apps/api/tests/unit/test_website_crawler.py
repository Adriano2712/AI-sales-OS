import socket

import httpx
import pytest

from app.modules.website_analysis.crawler import WebsiteCrawler, _is_dns_failure
from app.modules.website_analysis.enums import PageFetchOutcome, PageType


async def _fetch_with_handler(handler) -> tuple:
    crawler = WebsiteCrawler()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        signals, html = await crawler._fetch(client, "https://example.com/", PageType.HOMEPAGE)
    return signals, html


@pytest.mark.asyncio
async def test_403_response_is_classified_as_blocked():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="Forbidden")

    signals, _ = await _fetch_with_handler(handler)
    assert signals.fetch_outcome == PageFetchOutcome.BLOCKED
    assert signals.http_status == 403


@pytest.mark.asyncio
async def test_429_response_is_classified_as_blocked():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="Too Many Requests")

    signals, _ = await _fetch_with_handler(handler)
    assert signals.fetch_outcome == PageFetchOutcome.BLOCKED


@pytest.mark.asyncio
async def test_503_with_cloudflare_marker_is_classified_as_blocked():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="Checking your browser before accessing...")

    signals, _ = await _fetch_with_handler(handler)
    assert signals.fetch_outcome == PageFetchOutcome.BLOCKED


@pytest.mark.asyncio
async def test_503_without_any_challenge_marker_is_not_blocked():
    """A plain 503 (real maintenance page, say) has no anti-bot evidence —
    must not be guessed as a block."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="Service temporarily unavailable for maintenance")

    signals, _ = await _fetch_with_handler(handler)
    assert signals.fetch_outcome == PageFetchOutcome.RESPONDED


@pytest.mark.asyncio
async def test_plain_404_is_not_blocked():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    signals, _ = await _fetch_with_handler(handler)
    assert signals.fetch_outcome == PageFetchOutcome.RESPONDED
    assert signals.http_status == 404


@pytest.mark.asyncio
async def test_timeout_exception_is_classified_as_timeout():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out")

    signals, _ = await _fetch_with_handler(handler)
    assert signals.fetch_outcome == PageFetchOutcome.TIMEOUT
    assert signals.http_status is None


@pytest.mark.asyncio
async def test_connect_error_without_dns_cause_is_connection_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    signals, _ = await _fetch_with_handler(handler)
    assert signals.fetch_outcome == PageFetchOutcome.CONNECTION_ERROR


@pytest.mark.asyncio
async def test_connect_error_with_dns_cause_is_dns_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("getaddrinfo failed") from socket.gaierror(-2, "Name or service not known")

    signals, _ = await _fetch_with_handler(handler)
    assert signals.fetch_outcome == PageFetchOutcome.DNS_FAILURE


def test_is_dns_failure_true_for_real_gaierror():
    exc = ValueError("wrapped")
    exc.__cause__ = socket.gaierror(-2, "Name or service not known")
    assert _is_dns_failure(exc) is True


def test_is_dns_failure_false_for_unrelated_exception():
    assert _is_dns_failure(ValueError("something else")) is False
