from dataclasses import dataclass, field
from html import escape


@dataclass
class SiteDiagnosticEntry:
    """Only real, already-collected fields (spec section 35 — never invent a
    score, problem, or paragraph that isn't there yet)."""

    name: str
    city: str
    state: str
    website: str | None
    digital_score: float | None
    problems: list[str] = field(default_factory=list)
    ai_diagnostic: str | None = None


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
            score = entry.digital_score
            lines.append(f"  Score digital: {score if score is not None else 'ainda em análise'}")
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
            score = entry.digital_score
            score_text = str(score) if score is not None else "ainda em análise"
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
