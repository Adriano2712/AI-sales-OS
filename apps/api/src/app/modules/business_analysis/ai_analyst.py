from pydantic import BaseModel, Field

from app.modules.ai_gateway.base import AIRequest

_MODEL = "claude-sonnet-5"
"""Reasoning-heavy task (spec section 39: pick the model the task needs) —
synthesizing evidence into findings/problems and judging fit/compatibility
isn't the cheap classification work Haiku is for."""


class BusinessAnalysisAIOutput(BaseModel):
    """Validated by schema before ever being trusted (spec section 37).
    Bounded list lengths and score ranges are enforced here, not just hoped
    for in the prompt."""

    business_fit_score: int = Field(ge=0, le=100)
    compatibility_score: int = Field(ge=0, le=100)
    confidence: int = Field(
        ge=0,
        le=100,
        description="How confident the model is in these two scores, given the evidence it was shown — separate from the scores themselves (spec section 42).",
    )
    findings: list[str] = Field(max_length=8)
    problems: list[str] = Field(max_length=8)


_SYSTEM_PROMPT = """You are a business analyst evaluating whether a small local \
business would be a good prospect for a software house offering websites, \
e-commerce, automation, and internal-systems services.

Rules you must follow exactly:
- Base every finding and problem ONLY on the evidence and scores given to you \
below. Never invent a detail (a system, a competitor, a customer count, an \
opinion about quality) that isn't directly supported by what you were given.
- If the evidence is too thin to judge something, say so in `findings` rather \
than guessing — e.g. "Insufficient public evidence to assess X."
- `confidence` reflects how well-supported business_fit_score and \
compatibility_score are by the evidence you were given — not how good the \
business looks. A great-looking opportunity backed by thin evidence should \
get a high score and a LOW confidence, not a fabricated high confidence.
- findings and problems are short, factual sentences a salesperson could say \
out loud and defend. No marketing language, no invented specifics.
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
) -> AIRequest:
    """Pure — builds the request from already-fetched data, no I/O itself.
    `evidence_claims` is a list of (claim, confidence) pairs."""
    lines = [
        f"Company: {company_name}",
        f"Segment: {segment}",
        f"Location: {city}, {state}",
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
