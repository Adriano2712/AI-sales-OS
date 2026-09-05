from app.modules.website_analysis.enums import PageFetchOutcome, PageType, WebsiteStatus
from app.modules.website_analysis.scoring import SubScores
from app.modules.website_analysis.signal_extraction import PageSignals

# Quality-score thresholds for a *confidently* graded site — only reachable
# once evaluated_dimensions clears _MIN_CONFIDENT_DIMENSIONS below.
_GOOD_THRESHOLD = 70.0
_NEEDS_IMPROVEMENT_THRESHOLD = 40.0

# Out of 6 possible sub-score dimensions (funcionamento/mobile/ux/conversao/
# conteudo/design) — fewer than this and a GOOD/NEEDS_IMPROVEMENT/POOR
# verdict would be overclaiming from too little real content; ANALYZED is
# the honest "some real data, not enough to grade" middle state.
_MIN_CONFIDENT_DIMENSIONS = 4

# The only statuses backed by a real, confidently-observed page — the sole
# cases where WEBSITE_QUALITY_SCORE/WEBSITE_OPPORTUNITY_SCORE may carry a
# real number. Every other status (BLOCKED/TIMEOUT/WEBSITE_NOT_FOUND/
# JS_REQUIRED/OFFLINE/UNKNOWN) means "we didn't really see the site" — both
# scores must stay None for those, even though compute_sub_scores/
# compute_digital_score can still mechanically produce a number from
# whatever partial page data exists (e.g. a JS-only shell's near-empty HTML
# does parse to *some* low score) — service.py uses this set to null that
# number back out rather than let it silently contradict the status.
CONFIDENT_QUALITY_STATUSES = frozenset(
    {WebsiteStatus.GOOD, WebsiteStatus.NEEDS_IMPROVEMENT, WebsiteStatus.POOR, WebsiteStatus.ANALYZED}
)


def derive_website_status(
    pages: list[PageSignals], sub_scores: SubScores, quality_score: float | None
) -> WebsiteStatus:
    """The Fase 5 absolute rule, enforced in exactly one place: a technical
    failure to observe the site (timeout, DNS failure, anti-bot block, a
    JS-only shell this crawler can't render) is never scored as a *bad*
    website. Each of those maps to its own status — POOR/NEEDS_IMPROVEMENT/
    GOOD are only reachable from a confidently-evaluated, really-rendered
    page below."""
    if not pages:
        return WebsiteStatus.UNKNOWN

    homepage = next((p for p in pages if p.page_type == PageType.HOMEPAGE), pages[0])

    if homepage.fetch_outcome == PageFetchOutcome.TIMEOUT:
        return WebsiteStatus.TIMEOUT
    if homepage.fetch_outcome == PageFetchOutcome.DNS_FAILURE:
        return WebsiteStatus.WEBSITE_NOT_FOUND
    if homepage.fetch_outcome == PageFetchOutcome.BLOCKED:
        return WebsiteStatus.BLOCKED
    if homepage.fetch_outcome == PageFetchOutcome.CONNECTION_ERROR:
        return WebsiteStatus.OFFLINE

    homepage_ok = homepage.http_status is not None and homepage.http_status < 400
    if not homepage_ok:
        # A definitive HTTP error (404/500/502/...) with no anti-bot signal
        # detected — a real, observed failure, just not one of the more
        # specific reasons above.
        return WebsiteStatus.OFFLINE

    if homepage.looks_js_rendered:
        return WebsiteStatus.JS_REQUIRED

    if quality_score is None:
        return WebsiteStatus.UNKNOWN

    evaluated_dimensions = sum(
        1
        for dimension in (
            sub_scores.funcionamento,
            sub_scores.mobile,
            sub_scores.ux,
            sub_scores.conversao,
            sub_scores.conteudo,
            sub_scores.design,
        )
        if dimension is not None
    )
    if evaluated_dimensions < _MIN_CONFIDENT_DIMENSIONS:
        return WebsiteStatus.ANALYZED

    if quality_score >= _GOOD_THRESHOLD:
        return WebsiteStatus.GOOD
    if quality_score >= _NEEDS_IMPROVEMENT_THRESHOLD:
        return WebsiteStatus.NEEDS_IMPROVEMENT
    return WebsiteStatus.POOR
