import enum


class PageType(str, enum.Enum):
    HOMEPAGE = "HOMEPAGE"
    CONTACT = "CONTACT"
    ABOUT = "ABOUT"
    SERVICES = "SERVICES"
    SCHEDULING = "SCHEDULING"
    OTHER = "OTHER"


class PageFetchOutcome(str, enum.Enum):
    """How a single page fetch attempt actually went, beyond a bare HTTP
    status code (Fase 5). RESPONDED covers both a clean 2xx and a definitive
    4xx/5xx with no anti-bot signal detected — `http_status` already carries
    which. The other four values exist specifically so a WebsiteStatus can
    be derived without conflating "we couldn't observe the site" with "we
    observed a bad site" — the Fase 5 absolute rule."""

    RESPONDED = "RESPONDED"
    TIMEOUT = "TIMEOUT"
    DNS_FAILURE = "DNS_FAILURE"
    CONNECTION_ERROR = "CONNECTION_ERROR"
    BLOCKED = "BLOCKED"


class WebsiteStatus(str, enum.Enum):
    """Fase 5. ABSOLUTE RULE: a technical failure to observe the site
    (anti-bot block, timeout, DNS failure, a JS-only shell this crawler
    can't render) is never classified as POOR — POOR/NEEDS_IMPROVEMENT/GOOD
    are only reachable from a confidently-evaluated, really-rendered page
    (see status.py's derive_website_status). Everything else here means
    "insufficient or non-quality evidence", not "bad website".

    - WEBSITE_NOT_FOUND: the domain itself doesn't resolve (real DNS
      failure, not a guess from a message string).
    - OFFLINE: a real, observed connection/HTTP failure with no anti-bot
      signal detected (definitive 4xx/5xx, connection refused, or an
      unclassified transport error).
    - BLOCKED: a real anti-bot/WAF signal (403, 429, or a detected
      Cloudflare-style challenge response).
    - JS_REQUIRED: a 200 response whose content is a near-empty shell with a
      known SPA framework root marker — real content likely only exists
      after JavaScript runs, which this crawler deliberately never executes.
    - TIMEOUT: the request itself timed out.
    - UNKNOWN: real content couldn't be scored at all and none of the above
      more specific reasons applied.
    - ANALYZED: real content was fetched and partially scored, but too few
      dimensions were evaluable to confidently grade a tier.
    - GOOD / NEEDS_IMPROVEMENT / POOR: confidently graded from a real,
      rendered page's WEBSITE_QUALITY_SCORE.
    """

    WEBSITE_NOT_FOUND = "WEBSITE_NOT_FOUND"
    OFFLINE = "OFFLINE"
    BLOCKED = "BLOCKED"
    JS_REQUIRED = "JS_REQUIRED"
    TIMEOUT = "TIMEOUT"
    UNKNOWN = "UNKNOWN"
    ANALYZED = "ANALYZED"
    GOOD = "GOOD"
    NEEDS_IMPROVEMENT = "NEEDS_IMPROVEMENT"
    POOR = "POOR"
