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


_SYSTEM_PROMPT_TEMPLATE = """You are drafting a short first-contact outreach message on \
behalf of a real software house, to a small local business identified as a \
possible prospect.

Rules you must follow exactly (spec section 48):
- Use ONLY the sender identity, company name, segment, problem, potential \
solution, and evidence given to you below. Never invent a client, a result, \
a feature, a price, or any personal information (a person's name, a direct \
claim about who runs the business) that wasn't given to you.
- Never claim or imply the software house is physically located in the \
prospect's own city (e.g. never write something like "daqui de [cidade do \
prospect]"/"here in [prospect's city]"). If a real sender name/location is \
given below, you may state it plainly; if not, stay generic ("uma software \
house"/"a software house") without naming a place. Remote service is \
completely normal for this industry — never apologize for or draw attention \
to any distance.
- If the evidence is thin, keep the message general and honest rather than \
inventing specifics to sound more informed than you are.
- Tone: direct, respectful, brief — a real short message a human would \
actually send, not a marketing email. No exclamation-heavy language, no \
generic sales clichés.
- End with a low-friction question or call to action (e.g. asking if it's \
worth a quick conversation) — not a hard pitch.
- {language_instruction}
"""

# Every other rule above is language-independent — only this final line of
# the prompt changes. Keys match Message.language (messages/models.py).
_LANGUAGE_INSTRUCTIONS: dict[str, str] = {
    "pt-BR": "Write in Brazilian Portuguese, matching how a Brazilian software "
    "house would actually write to a prospect.",
    "en": "Write in natural, professional English, matching how a software "
    "house would actually write a first-contact message to a prospect.",
}
_DEFAULT_LANGUAGE = "pt-BR"


def default_language_for_country(country: str) -> str:
    """Best-effort default when the caller doesn't pick a language explicitly
    — Brazilian companies get Portuguese, everything else gets English
    (the only two the AI Writer actually supports today, see
    _LANGUAGE_INSTRUCTIONS). Never silently writes Portuguese to a company
    outside Brazil just because that's historically all this system did."""
    return _DEFAULT_LANGUAGE if country == "BR" else "en"


def build_ai_request(
    company_name: str,
    segment: str,
    city: str,
    problem: str | None,
    potential_solution: str | None,
    reasons: list[str],
    sender_name: str | None = None,
    sender_location: str | None = None,
    language: str = _DEFAULT_LANGUAGE,
) -> AIRequest:
    """Pure — builds the request from already-fetched data, no I/O itself."""
    system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(
        language_instruction=_LANGUAGE_INSTRUCTIONS.get(
            language, _LANGUAGE_INSTRUCTIONS[_DEFAULT_LANGUAGE]
        )
    )

    sender_line = "UNKNOWN — do not name a specific software house or place"
    if sender_name:
        sender_line = sender_name + (f", based in {sender_location}" if sender_location else "")

    lines = [
        f"Sender (the real software house sending this message): {sender_line}",
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
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        output_schema=MessageAIOutput,
        model=_MODEL,
    )
