from dataclasses import dataclass, field
from html import escape


@dataclass
class SiteDiagnosticEntry:
    """Only real, already-collected fields (spec section 35 — never invent a
    score, problem, or paragraph that isn't there yet).

    Fase 10: `website_status` (WebsiteStatus.value, Fase 5) lets the email
    say *why* no digital_score exists instead of a generic "ainda em
    análise" — e.g. a real anti-bot block or timeout, never mislabeled as
    a bad site (the absolute rule, extended to the digest's own wording)."""

    name: str
    city: str
    state: str
    website: str | None
    digital_score: float | None
    problems: list[str] = field(default_factory=list)
    ai_diagnostic: str | None = None
    website_status: str | None = None


# Fase 5's WebsiteStatus values that mean "we couldn't really observe the
# site" — worded here so the digest never implies a bad site for one of
# these (mirrors website_analysis/scoring.py's own problem messages).
_INSUFFICIENT_EVIDENCE_STATUS_LABELS: dict[str, str] = {
    "BLOCKED": "bloqueio automático detectado — não foi possível confirmar o conteúdo real",
    "TIMEOUT": "não respondeu a tempo — não foi possível confirmar o conteúdo real",
    "JS_REQUIRED": "depende de JavaScript — não foi possível confirmar o conteúdo real",
    "WEBSITE_NOT_FOUND": "domínio não pôde ser resolvido",
    "OFFLINE": "fora do ar no momento da verificação",
    "UNKNOWN": "não foi possível avaliar com as evidências disponíveis",
}


def _digital_score_line(digital_score: float | None, website_status: str | None) -> str:
    if digital_score is not None:
        return str(digital_score)
    if website_status and website_status in _INSUFFICIENT_EVIDENCE_STATUS_LABELS:
        return _INSUFFICIENT_EVIDENCE_STATUS_LABELS[website_status]
    return "ainda em análise"


def build_site_digest_subject(date_str: str, segment: str, count: int) -> str:
    if count == 0:
        return f"AI Sales OS — diagnóstico de sites — nenhum site novo hoje ({segment}, {date_str})"
    return f"AI Sales OS — diagnóstico de sites — {count} empresa(s) hoje ({segment}, {date_str})"


def build_site_digest_text(entries: list[SiteDiagnosticEntry], date_str: str, segment: str) -> str:
    header = f"Diagnóstico de sites — {date_str} — segmento: {segment}"
    if not entries:
        return f"{header}\n\nNenhuma empresa nova encontrada hoje."

    lines = [header, ""]
    for entry in entries:
        lines.append(f"- {entry.name} ({entry.city}/{entry.state})")
        if entry.website is None:
            lines.append("  Site: não possui — nenhuma presença digital própria encontrada.")
        else:
            lines.append(f"  Site: {entry.website}")
            lines.append(f"  Score digital: {_digital_score_line(entry.digital_score, entry.website_status)}")
            if entry.problems:
                lines.append("  Problemas encontrados:")
                for problem in entry.problems:
                    lines.append(f"   - {problem}")
            if entry.ai_diagnostic:
                lines.append(f"  Impacto: {entry.ai_diagnostic}")
        lines.append("")
    return "\n".join(lines)


def build_site_digest_html(entries: list[SiteDiagnosticEntry], date_str: str, segment: str) -> str:
    header = f"<h2>Diagnóstico de sites — {escape(date_str)} — segmento: {escape(segment)}</h2>"
    if not entries:
        return f"{header}<p>Nenhuma empresa nova encontrada hoje.</p>"

    blocks = []
    for entry in entries:
        title = f"<h3 style='margin-bottom:2px'>{escape(entry.name)} — {escape(entry.city)}/{escape(entry.state)}</h3>"
        if entry.website is None:
            body = "<p>Site: <strong>não possui</strong> — nenhuma presença digital própria encontrada.</p>"
        else:
            score_text = escape(_digital_score_line(entry.digital_score, entry.website_status))
            parts = [
                f"<p>Site: {escape(entry.website)}<br>Score digital: <strong>{score_text}</strong></p>"
            ]
            if entry.problems:
                items = "".join(f"<li>{escape(p)}</li>" for p in entry.problems)
                parts.append(f"<p>Problemas encontrados:</p><ul>{items}</ul>")
            if entry.ai_diagnostic:
                parts.append(f"<p><em>{escape(entry.ai_diagnostic)}</em></p>")
            body = "".join(parts)
        blocks.append(
            f"<div style='padding:10px 0;border-bottom:1px solid #eee'>{title}{body}</div>"
        )

    return f"<div style='font-family:sans-serif;font-size:14px'>{header}{''.join(blocks)}</div>"
