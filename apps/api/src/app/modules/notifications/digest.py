from dataclasses import dataclass
from html import escape


@dataclass
class DigestCompanyEntry:
    """Only real, already-collected fields (spec section 35 — never invent
    a score/classification that isn't there yet; "ainda em análise" is the
    honest UNKNOWN, not a guess)."""

    name: str
    segment: str
    city: str
    state: str
    phone: str | None
    website: str | None
    overall_score: float | None
    classification: str | None


def build_digest_subject(date_str: str, segment: str, count: int) -> str:
    if count == 0:
        return f"AI Sales OS — nenhuma empresa nova hoje ({segment}, {date_str})"
    return f"AI Sales OS — {count} empresa(s) nova(s) hoje ({segment}, {date_str})"


def build_digest_text(entries: list[DigestCompanyEntry], date_str: str, segment: str) -> str:
    header = f"Descoberta diária — {date_str} — segmento: {segment}"
    if not entries:
        return f"{header}\n\nNenhuma empresa nova encontrada hoje."

    lines = [header, ""]
    for entry in entries:
        lines.append(f"- {entry.name} ({entry.city}/{entry.state})")
        lines.append(f"  Telefone: {entry.phone or 'não informado'}")
        lines.append(f"  Site: {entry.website or 'não informado'}")
        if entry.overall_score is not None:
            classification = entry.classification or "sem classificação"
            lines.append(f"  Score de negócio: {entry.overall_score} ({classification})")
        else:
            lines.append("  Análise: ainda em andamento")
        lines.append("")
    return "\n".join(lines)


def build_digest_html(entries: list[DigestCompanyEntry], date_str: str, segment: str) -> str:
    header = f"<h2>Descoberta diária — {escape(date_str)} — segmento: {escape(segment)}</h2>"
    if not entries:
        return f"{header}<p>Nenhuma empresa nova encontrada hoje.</p>"

    rows = []
    for entry in entries:
        score_cell = (
            f"{entry.overall_score} ({escape(entry.classification or 'sem classificação')})"
            if entry.overall_score is not None
            else "ainda em análise"
        )
        rows.append(
            "<tr>"
            f"<td style='padding:4px 8px;border-bottom:1px solid #eee'>{escape(entry.name)}</td>"
            f"<td style='padding:4px 8px;border-bottom:1px solid #eee'>{escape(entry.city)}/{escape(entry.state)}</td>"
            f"<td style='padding:4px 8px;border-bottom:1px solid #eee'>{escape(entry.phone or 'não informado')}</td>"
            f"<td style='padding:4px 8px;border-bottom:1px solid #eee'>{escape(entry.website or 'não informado')}</td>"
            f"<td style='padding:4px 8px;border-bottom:1px solid #eee'>{score_cell}</td>"
            "</tr>"
        )

    table = (
        "<table style='border-collapse:collapse;font-family:sans-serif;font-size:14px'>"
        "<tr style='text-align:left;color:#666'>"
        "<th style='padding:4px 8px'>Empresa</th><th style='padding:4px 8px'>Cidade</th>"
        "<th style='padding:4px 8px'>Telefone</th><th style='padding:4px 8px'>Site</th>"
        "<th style='padding:4px 8px'>Score</th></tr>" + "".join(rows) + "</table>"
    )
    return f"<div style='font-family:sans-serif'>{header}{table}</div>"
