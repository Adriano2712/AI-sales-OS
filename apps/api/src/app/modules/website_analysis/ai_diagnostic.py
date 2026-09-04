from pydantic import BaseModel, Field

from app.modules.ai_gateway.base import AIRequest

_MODEL = "claude-sonnet-5"
"""Same reasoning-heavy justification as business_analysis/ai_analyst.py —
turning a list of concrete problems into a plain-language business
explanation is synthesis, not the cheap classification work Haiku is for."""


class SiteDiagnosticAIOutput(BaseModel):
    """Validated by schema before ever being trusted (spec section 37)."""

    business_impact: str = Field(max_length=800)


_SYSTEM_PROMPT = """You are a website consultant writing a short, plain-language \
explanation for a small business owner about problems found on their own website.

Rules you must follow exactly:
- Base the explanation ONLY on the concrete problems and score given below. \
Never invent a detail (traffic numbers, competitors, customer counts, an \
opinion about quality) that isn't directly supported by what you were given.
- Write in Brazilian Portuguese, in a direct, non-salesy tone — a real \
consultant explaining findings, not a marketing pitch.
- One short paragraph (3-5 sentences) connecting the concrete problems to \
plain business consequences (e.g. no phone link = a visitor who wanted to \
call gives up), not generic advice.
- If no concrete problems were found, say so honestly instead of inventing \
something to fix.
"""


def build_ai_request(
    company_name: str,
    segment: str,
    digital_score: float | None,
    problems: list[str],
) -> AIRequest:
    """Pure — builds the request from already-computed data, no I/O itself."""
    lines = [
        f"Company: {company_name}",
        f"Segment: {segment}",
        f"Digital score (0-100, already computed deterministically): "
        f"{digital_score if digital_score is not None else 'UNKNOWN'}",
        "",
    ]

    if problems:
        lines.append("Concrete problems found on the site:")
        for problem in problems:
            lines.append(f"- {problem}")
    else:
        lines.append("No concrete problems were found on the site.")

    user_prompt = "\n".join(lines)

    return AIRequest(
        task="site_diagnostic",
        system_prompt=_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        output_schema=SiteDiagnosticAIOutput,
        model=_MODEL,
    )
