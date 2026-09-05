from pydantic import BaseModel, Field, field_validator

from app.modules.ai_gateway.base import AIRequest

_MODEL = "claude-sonnet-5"
"""Reasoning-heavy task (spec section 39: pick the model the task needs) —
synthesizing evidence into findings/problems and judging fit/compatibility
isn't the cheap classification work Haiku is for."""

_DEFAULT_SERVICES = ("websites", "e-commerce", "automation", "internal-systems")
"""Fallback service list used when a campaign hasn't stated its own
`services` (Fase 6) — the exact same generic description business_fit_score
was already scored against before service_fit_score existed, so a campaign
with no stated services sees service_fit_score track business_fit_score
closely rather than getting a fabricated, unrelated number."""

# Fase 6 absolute rule, enforced in code (not just prompted) — same
# discipline as evidence/service.py's InvalidEvidencePolarity check: this
# system's own opportunity signals are strictly signal-based ("potential",
# "signals suggest"), never an assertive claim about what a business has
# decided to do. Checked in both English and Portuguese since messages and
# analysis can be produced in either.
_BANNED_BUYING_PHRASES = (
    "wants to buy",
    "will buy",
    "is going to buy",
    "has decided to buy",
    "wants to purchase",
    "will purchase",
    "ready to buy",
    "quer comprar",
    "vai comprar",
    "decidiu comprar",
    "está pronto para comprar",
    "pretende comprar",
)


class BusinessAnalysisAIOutput(BaseModel):
    """Validated by schema before ever being trusted (spec section 37).
    Bounded list lengths and score ranges are enforced here, not just hoped
    for in the prompt."""

    business_fit_score: int = Field(ge=0, le=100)
    compatibility_score: int = Field(ge=0, le=100)
    # Fase 6: fit against the *specific* service(s) a campaign is selling
    # (see build_ai_request's `services` param) — distinct from
    # business_fit_score, which judges general prospect quality for a
    # software house regardless of which service would actually be pitched.
    service_fit_score: int = Field(ge=0, le=100)
    # Fase 6: strength of observed buying-related signals — never a
    # probability or claim of actual purchase intent. See
    # buying_potential_summary's validator for the enforced language rule.
    buying_potential_score: int = Field(ge=0, le=100)
    buying_potential_summary: str = Field(
        max_length=300,
        description=(
            "One hedged, signal-based sentence (e.g. 'Several signals suggest "
            "digital investment potential' / 'Weak signals; likely not a near-term "
            "opportunity'). Never assert what the business wants or has decided — "
            "describe observed signals only."
        ),
    )
    confidence: int = Field(
        ge=0,
        le=100,
        description="How confident the model is in these scores, given the evidence it was shown — separate from the scores themselves (spec section 42).",
    )
    findings: list[str] = Field(max_length=8)
    problems: list[str] = Field(max_length=8)

    @field_validator("buying_potential_summary")
    @classmethod
    def _reject_assertive_buying_language(cls, value: str) -> str:
        lowered = value.lower()
        for phrase in _BANNED_BUYING_PHRASES:
            if phrase in lowered:
                raise ValueError(
                    "buying_potential_summary must use hedged signal-based language "
                    f"(e.g. 'signals suggest potential') — found an assertive purchase-"
                    f"intent phrase: {phrase!r}"
                )
        return value


_SYSTEM_PROMPT = """You are a business analyst evaluating whether a small local \
business would be a good prospect for a software house offering websites, \
e-commerce, automation, and internal-systems services.

Rules you must follow exactly:
- Base every finding and problem ONLY on the evidence and scores given to you \
below. Never invent a detail (a system, a competitor, a customer count, an \
opinion about quality) that isn't directly supported by what you were given.
- If the evidence is too thin to judge something, say so in `findings` rather \
than guessing — e.g. "Insufficient public evidence to assess X."
- `confidence` reflects how well-supported your scores are by the evidence you \
were given — not how good the business looks. A great-looking opportunity \
backed by thin evidence should get a high score and a LOW confidence, not a \
fabricated high confidence.
- findings and problems are short, factual sentences a salesperson could say \
out loud and defend. No marketing language, no invented specifics.
- `service_fit_score` judges fit specifically against the "Services being \
sold in this campaign" listed below — not a generic impression. It is a \
different question from business_fit_score (general prospect quality) and \
the two may reasonably differ.
- `buying_potential_score`/`buying_potential_summary` describe the STRENGTH \
OF OBSERVED SIGNALS only (e.g. digital gaps, activity level, review volume) \
— never a claim about what the business wants, intends, or has decided. \
Write buying_potential_summary the way a cautious analyst would: "Several \
signals suggest digital investment potential", never "This business wants \
to buy a website." Never guess at revenue, employee count, or budget — \
none of that was given to you and none of it is observable from public \
evidence.
"""


def build_ai_request(
    company_name: str,
    segment: str,
    city: str,
    state: str,
    digital_maturity_score: float | None,
    activity_score: float | None,
    need_score: float | None,
    website_findings: dict | None,
    evidence_claims: list[tuple[str, str]],
    services: list[str] | None = None,
) -> AIRequest:
    """Pure — builds the request from already-fetched data, no I/O itself.
    `evidence_claims` is a list of (claim, confidence) pairs. `services` is
    the campaign's own stated service list (Fase 6) — falls back to the
    generic software-house description when empty/not provided, matching
    what business_fit_score was already scored against before this field
    existed."""
    services_line = (
        f"Services being sold in this campaign: {', '.join(services)}"
        if services
        else "No specific services were defined for this campaign — use the "
        f"general software-house services ({', '.join(_DEFAULT_SERVICES)}) as the "
        "reference for service_fit_score."
    )
    lines = [
        f"Company: {company_name}",
        f"Segment: {segment}",
        f"Location: {city}, {state}",
        services_line,
        "",
        "Scores already computed deterministically (do not recompute these,"
        " just use them as context):",
        f"- digital_maturity_score: {digital_maturity_score if digital_maturity_score is not None else 'UNKNOWN'}",
        f"- activity_score: {activity_score if activity_score is not None else 'UNKNOWN'}",
        f"- need_score: {need_score if need_score is not None else 'UNKNOWN'}",
        "",
    ]

    if website_findings:
        lines.append("Website analysis findings:")
        for key, value in website_findings.items():
            lines.append(f"- {key}: {value}")
        lines.append("")

    if evidence_claims:
        lines.append("Public evidence collected about this company:")
        for claim, confidence in evidence_claims:
            lines.append(f"- [{confidence}] {claim}")
    else:
        lines.append("No additional public evidence was collected for this company.")

    user_prompt = "\n".join(lines)

    return AIRequest(
        task="business_analysis",
        system_prompt=_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        output_schema=BusinessAnalysisAIOutput,
        model=_MODEL,
    )
