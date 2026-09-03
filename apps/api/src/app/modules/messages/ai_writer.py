from pydantic import BaseModel, Field

from app.modules.ai_gateway.base import AIRequest

_MODEL = "claude-sonnet-5"
"""Reasoning-heavy task (spec section 39, per docs/AI.md's per-task model
guidance — "message generation" is explicitly listed as a Sonnet task, same
tier as business analysis): writing a message a real salesperson could
defend isn't cheap classification work."""


class MessageAIOutput(BaseModel):
    """Validated by schema before ever being trusted (spec section 37)."""

    text: str = Field(min_length=1, max_length=2000)


_SYSTEM_PROMPT = """You are drafting a short first-contact outreach message on \
behalf of a software house, to a small local business identified as a \
possible prospect.

Rules you must follow exactly (spec section 48):
- Use ONLY the company name, segment, problem, potential solution, and \
evidence given to you below. Never invent a client, a result, a feature, a \
price, or any personal information (a person's name, a direct claim about \
who runs the business) that wasn't given to you.
- If the evidence is thin, keep the message general and honest rather than \
inventing specifics to sound more informed than you are.
- Tone: direct, respectful, brief — a real short message a human would \
actually send, not a marketing email. No exclamation-heavy language, no \
generic sales clichés.
- End with a low-friction question or call to action (e.g. asking if it's \
worth a quick conversation) — not a hard pitch.
- Write in Brazilian Portuguese, matching how a Brazilian software house \
would actually write to a local business owner.
"""


def build_ai_request(
    company_name: str,
    segment: str,
    city: str,
    problem: str | None,
    potential_solution: str | None,
    reasons: list[str],
) -> AIRequest:
    """Pure — builds the request from already-fetched data, no I/O itself."""
    lines = [
        f"Company: {company_name}",
        f"Segment: {segment}",
        f"Location: {city}",
        "",
        f"Problem identified: {problem or 'UNKNOWN — no specific problem identified yet'}",
        f"Potential solution: {potential_solution or 'UNKNOWN — no specific solution identified yet'}",
        "",
    ]
    if reasons:
        lines.append("Supporting reasons (from the business analysis):")
        for reason in reasons:
            lines.append(f"- {reason}")
    else:
        lines.append("No additional supporting reasons were recorded.")

    user_prompt = "\n".join(lines)

    return AIRequest(
        task="message_generation",
        system_prompt=_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        output_schema=MessageAIOutput,
        model=_MODEL,
    )
