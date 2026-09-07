from dataclasses import dataclass, field
from html import escape


@dataclass
class DigestCompanyEntry:
    """Only real, already-collected fields (spec section 35 — never invent
    a score/classification that isn't there yet; "ainda em análise" is the
    honest UNKNOWN, not a guess).

    Fase 10 additions (opportunity_score onward) are all optional with safe
    defaults — every one of them is data `workers/scheduler.py`'s
    `_send_digest_for_run` already has in scope by the time it builds an
    entry (the same `opportunity`/`analysis`/`company` objects it already
    queries for the fields above), never a new DB round-trip."""

    name: str
    segment: str
    city: str
    state: str
    phone: str | None
    website: str | None
    overall_score: float | None
    classification: str | None
    opportunity_score: float | None = None
    opportunity_confidence: float | None = None
    service_fit_score: float | None = None
    buying_potential_summary: str | None = None
    google_rating: float | None = None
    google_review_count: int | None = None
    instagram_url: str | None = None
    reasons: list[str] = field(default_factory=list)


@dataclass
class DigestSummary:
    """Pure aggregate over a run's entries — spec's "summary counters" for
    the daily report. Never invents a bucket: a company with no
    classification yet is counted separately (`unscored`), not silently
    dropped or guessed into LOW."""

    total: int
    high: int
    good: int
    review: int
    low: int
    unscored: int
    average_opportunity_score: float | None


def build_digest_summary(entries: list[DigestCompanyEntry]) -> DigestSummary:
    """Pure — tallies classifications and averages already-known
    opportunity scores. No DB access, no guessing: a company whose scoring
    hasn't completed yet (classification/opportunity_score still None)
    contributes to `unscored`/is excluded from the average, never
    defaulted into a bucket it hasn't earned."""
    high = sum(1 for e in entries if e.classification == "HIGH")
    good = sum(1 for e in entries if e.classification == "GOOD")
    review = sum(1 for e in entries if e.classification == "REVIEW")
    low = sum(1 for e in entries if e.classification == "LOW")
    unscored = sum(1 for e in entries if e.classification is None)
    scores = [e.opportunity_score for e in entries if e.opportunity_score is not None]
    average = round(sum(scores) / len(scores), 1) if scores else None
    return DigestSummary(
        total=len(entries),
        high=high,
        good=good,
        review=review,
        low=low,
        unscored=unscored,
        average_opportunity_score=average,
    )


def _summary_breakdown_parts(summary: DigestSummary) -> list[str]:
    parts = []
    if summary.high:
        parts.append(f"{summary.high} HIGH")
    if summary.good:
        parts.append(f"{summary.good} GOOD")
    if summary.review:
        parts.append(f"{summary.review} REVIEW")
    if summary.low:
        parts.append(f"{summary.low} LOW")
    if summary.unscored:
        parts.append(f"{summary.unscored} ainda em análise")
    return parts


def build_digest_subject(date_str: str, segment: str, count: int) -> str:
    if count == 0:
        return f"AI Sales OS — nenhuma empresa nova hoje ({segment}, {date_str})"
    return f"AI Sales OS — {count} empresa(s) nova(s) hoje ({segment}, {date_str})"


def build_digest_text(
    entries: list[DigestCompanyEntry],
    date_str: str,
    segment: str,
    summary: DigestSummary | None = None,
) -> str:
    header = f"Descoberta diária — {date_str} — segmento: {segment}"
    if not entries:
        return f"{header}\n\nNenhuma empresa nova encontrada hoje."

    lines = [header]
    if summary is not None:
        breakdown = _summary_breakdown_parts(summary)
        summary_line = f"Resumo: {summary.total} oportunidade(s)"
        if breakdown:
            summary_line += " (" + ", ".join(breakdown) + ")"
        if summary.average_opportunity_score is not None:
            summary_line += f" — score médio de oportunidade: {summary.average_opportunity_score}"
        lines.append(summary_line)
    lines.append("")

    for entry in entries:
        lines.append(f"- {entry.name} ({entry.city}/{entry.state})")
        lines.append(f"  Telefone: {entry.phone or 'não informado'}")
        lines.append(f"  Site: {entry.website or 'não informado'}")
        if entry.overall_score is not None:
            classification = entry.classification or "sem classificação"
            lines.append(f"  Score de negócio: {entry.overall_score} ({classification})")
        else:
            lines.append("  Análise: ainda em andamento")
        if entry.opportunity_score is not None:
            confidence_part = (
                f" (confiança: {entry.opportunity_confidence})"
                if entry.opportunity_confidence is not None
                else ""
            )
            lines.append(f"  Oportunidade: {entry.opportunity_score}{confidence_part}")
        if entry.service_fit_score is not None:
            lines.append(f"  Fit de serviço: {entry.service_fit_score}")
        if entry.google_rating is not None:
            reviews_part = (
                f" ({entry.google_review_count} avaliações)"
                if entry.google_review_count is not None
                else ""
            )
            lines.append(f"  Google: {entry.google_rating}{reviews_part}")
        if entry.instagram_url:
            lines.append(f"  Instagram: {entry.instagram_url}")
        if entry.buying_potential_summary:
            lines.append(f"  Sinais: {entry.buying_potential_summary}")
        if entry.reasons:
            lines.append(f"  Motivos: {'; '.join(entry.reasons)}")
        lines.append("")
    return "\n".join(lines)


def build_digest_html(
    entries: list[DigestCompanyEntry],
    date_str: str,
    segment: str,
    summary: DigestSummary | None = None,
) -> str:
    header = f"<h2>Descoberta diária — {escape(date_str)} — segmento: {escape(segment)}</h2>"
    if not entries:
        return f"{header}<p>Nenhuma empresa nova encontrada hoje.</p>"

    summary_html = ""
    if summary is not None:
        breakdown = _summary_breakdown_parts(summary)
        summary_text = f"{summary.total} oportunidade(s)"
        if breakdown:
            summary_text += " (" + ", ".join(escape(p) for p in breakdown) + ")"
        if summary.average_opportunity_score is not None:
            summary_text += f" — score médio de oportunidade: {summary.average_opportunity_score}"
        summary_html = (
            f"<p style='font-family:sans-serif;font-size:14px;color:#333'>"
            f"<strong>Resumo:</strong> {summary_text}</p>"
        )

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

        # Fase 10 detail row — richer signals, only rendered when there's
        # something real to show (never an empty/fabricated line).
        detail_parts = []
        if entry.opportunity_score is not None:
            confidence_part = (
                f" (confiança: {entry.opportunity_confidence})"
                if entry.opportunity_confidence is not None
                else ""
            )
            detail_parts.append(f"Oportunidade: {entry.opportunity_score}{confidence_part}")
        if entry.service_fit_score is not None:
            detail_parts.append(f"Fit de serviço: {entry.service_fit_score}")
        if entry.google_rating is not None:
            reviews_part = (
                f" ({entry.google_review_count} avaliações)"
                if entry.google_review_count is not None
                else ""
            )
            detail_parts.append(f"Google: {entry.google_rating}{reviews_part}")
        if entry.instagram_url:
            detail_parts.append(f"Instagram: {escape(entry.instagram_url)}")
        detail_line = " · ".join(detail_parts)

        extra_lines = []
        if detail_line:
            extra_lines.append(detail_line)
        if entry.buying_potential_summary:
            extra_lines.append(f"<em>{escape(entry.buying_potential_summary)}</em>")
        if entry.reasons:
            extra_lines.append("Motivos: " + "; ".join(escape(r) for r in entry.reasons))

        if extra_lines:
            rows.append(
                "<tr><td colspan='5' style='padding:0 8px 8px 8px;border-bottom:1px solid #eee;"
                "font-size:12px;color:#555'>" + "<br>".join(extra_lines) + "</td></tr>"
            )

    table = (
        "<table style='border-collapse:collapse;font-family:sans-serif;font-size:14px'>"
        "<tr style='text-align:left;color:#666'>"
        "<th style='padding:4px 8px'>Empresa</th><th style='padding:4px 8px'>Cidade</th>"
        "<th style='padding:4px 8px'>Telefone</th><th style='padding:4px 8px'>Site</th>"
        "<th style='padding:4px 8px'>Score</th></tr>" + "".join(rows) + "</table>"
    )
    return f"<div style='font-family:sans-serif'>{header}{summary_html}{table}</div>"
