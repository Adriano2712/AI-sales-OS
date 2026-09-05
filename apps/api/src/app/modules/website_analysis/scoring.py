from dataclasses import dataclass

from app.modules.website_analysis.enums import PageType, WebsiteStatus
from app.modules.website_analysis.signal_extraction import PageSignals

# Order mirrors the priority a business owner would care about, not a score
# weight — the digest and company-detail page just render this list top to
# bottom.
_VIEWPORT_PROBLEM = (
    "Site não é otimizado para celular (sem meta viewport) — a maioria dos "
    "visitantes acessa pelo celular."
)
_NO_CONTACT_PROBLEM = (
    "Nenhuma forma direta de contato encontrada no site (sem formulário, "
    "telefone clicável, e-mail ou WhatsApp)."
)
_NO_NAV_PROBLEM = "Página inicial sem menu de navegação — dificulta encontrar informação."
_NO_SERVICES_PAGE_PROBLEM = "Nenhuma página de serviços/produtos encontrada."
_MISSING_TITLE_OR_DESCRIPTION_PROBLEM = (
    "Título ou descrição da página ausentes — prejudica o posicionamento no Google (SEO)."
)
_THIN_CONTENT_PROBLEM = "Conteúdo da página inicial muito raso (poucas palavras)."
# Fase 5 — real technical failures that must never read as a quality
# judgment (the absolute rule). Deliberately doesn't say "site ruim"/"site
# fora do ar" for these three: we didn't actually observe the site's real
# content, so there's nothing to judge.
_BLOCKED_PROBLEM = (
    "Não foi possível confirmar o conteúdo do site — a resposta indica um "
    "bloqueio automático (proteção anti-bot/WAF), não necessariamente um "
    "problema real do site."
)
_TIMEOUT_PROBLEM = (
    "O site demorou demais para responder — não foi possível confirmar seu conteúdo real."
)
_WEBSITE_NOT_FOUND_PROBLEM = (
    "O domínio informado não pôde ser resolvido (pode estar expirado, "
    "incorreto ou fora do ar permanentemente)."
)
_JS_REQUIRED_PROBLEM = (
    "O site parece depender de JavaScript para exibir o conteúdo — este "
    "diagnóstico não executa JavaScript, então a qualidade real não pôde ser confirmada."
)

# Spec section 32.
WEIGHTS: dict[str, float] = {
    "funcionamento": 0.20,
    "mobile": 0.20,
    "ux": 0.15,
    "conversao": 0.20,
    "conteudo": 0.15,
    "design": 0.10,
}


@dataclass
class SubScores:
    funcionamento: float | None
    mobile: float | None
    ux: float | None
    conversao: float | None
    conteudo: float | None
    design: float | None


def compute_sub_scores(pages: list[PageSignals]) -> SubScores:
    """Pure — spec section 32: a dimension that can't be evaluated stays
    `None`, never a fabricated number. Unit tested exhaustively."""
    if not pages:
        return SubScores(None, None, None, None, None, None)

    homepage = next((p for p in pages if p.page_type == PageType.HOMEPAGE), pages[0])
    homepage_ok = homepage.http_status is not None and homepage.http_status < 400

    if not homepage_ok:
        # Fase 5 fix: an unreachable homepage is *absence* of evidence, not
        # evidence of a bad site — funcionamento used to be computed as 0.0
        # here (0 of N pages responded), which then single-handedly dragged
        # compute_digital_score to 0.0 (100% of the renormalized weight,
        # since every other dimension was already None): a timed-out/
        # blocked/nonexistent site was being scored as literally the worst
        # possible *quality*, indistinguishable from a real, rendered, truly
        # terrible page. Confirmed as a live bug against this project's own
        # real data — 403-blocked sites had all been scored digital_score=0.0
        # (see database/migrations/versions/0016_website_status.py). Status
        # classification for *why* (OFFLINE/TIMEOUT/BLOCKED/WEBSITE_NOT_FOUND)
        # lives in status.py; scoring now stays silent instead.
        return SubScores(
            funcionamento=None, mobile=None, ux=None, conversao=None, conteudo=None, design=None,
        )

    successful = [p for p in pages if p.http_status is not None and p.http_status < 400]
    funcionamento = round(100.0 * len(successful) / len(pages), 1)

    mobile = 100.0 if homepage.has_viewport_meta else 0.0

    nav_bonus = 1.0 if homepage.has_nav else 0.7
    ux = round(min(100.0, 100.0 * (len(successful) / len(pages)) * nav_bonus), 1)

    conversao_signals = [
        any(p.has_contact_form for p in pages),
        any(p.has_phone_link for p in pages),
        any(p.has_email_link for p in pages),
        any(p.has_whatsapp_link for p in pages),
        any(p.page_type == PageType.CONTACT for p in pages),
    ]
    conversao = round(100.0 * sum(conversao_signals) / len(conversao_signals), 1)

    conteudo_signals = [
        bool(homepage.title),
        bool(homepage.meta_description),
        homepage.word_count >= 100,
        any(p.page_type == PageType.SERVICES for p in pages),
    ]
    conteudo = round(100.0 * sum(conteudo_signals) / len(conteudo_signals), 1)

    # Weak positive-only signal (spec section 35: never assert an absence we
    # can't support). Presence of a linked stylesheet is weak evidence of
    # deliberate design effort; absence proves nothing without rendering the
    # page, so it stays UNKNOWN rather than being scored as bad design.
    design = 100.0 if homepage.has_custom_stylesheet else None

    return SubScores(funcionamento, mobile, ux, conversao, conteudo, design)


def compute_digital_score(sub_scores: SubScores) -> float | None:
    """Weighted average over only the evaluated dimensions, weights
    renormalized to what's available — never fills a gap with a guess."""
    parts = [
        (sub_scores.funcionamento, WEIGHTS["funcionamento"]),
        (sub_scores.mobile, WEIGHTS["mobile"]),
        (sub_scores.ux, WEIGHTS["ux"]),
        (sub_scores.conversao, WEIGHTS["conversao"]),
        (sub_scores.conteudo, WEIGHTS["conteudo"]),
        (sub_scores.design, WEIGHTS["design"]),
    ]
    evaluated = [(score, weight) for score, weight in parts if score is not None]
    if not evaluated:
        return None

    total_weight = sum(weight for _, weight in evaluated)
    weighted_sum = sum(score * weight for score, weight in evaluated)
    return round(weighted_sum / total_weight, 1)


def compute_opportunity_score(sub_scores: SubScores) -> float | None:
    """WEBSITE_OPPORTUNITY_SCORE (Fase 5) — deliberately distinct from
    WEBSITE_QUALITY_SCORE (compute_digital_score). A well-built, fast site
    can still be a real sales opportunity if it converts poorly (spec's own
    positive examples: "CTA fraca", "sem WhatsApp") — a single blended
    quality number would dilute exactly that signal. Scoped to the
    conversao (contact/CTA) dimension specifically, not the whole site, and
    stays None whenever conversao itself couldn't be evaluated — never
    guessed from a fetch failure (the same absence as compute_digital_score
    inherits from compute_sub_scores's Fase 5 fix)."""
    if sub_scores.conversao is None:
        return None
    return round(100.0 - sub_scores.conversao, 1)


def derive_problems(pages: list[PageSignals], status: WebsiteStatus) -> list[str]:
    """Concrete, human-readable diagnostics drawn directly from observed page
    signals — same evaluability discipline as compute_sub_scores (spec
    section 35): never states a problem for something that wasn't actually
    observed. If the homepage didn't load, that's the only problem reported —
    nothing else was meaningfully fetched, so nothing else is asserted.

    Fase 5: `status` (already derived by status.py's derive_website_status)
    decides which branch applies — BLOCKED/TIMEOUT/WEBSITE_NOT_FOUND/
    JS_REQUIRED each get their own message that doesn't call it a bad site,
    per the absolute rule. Only OFFLINE keeps the old "site fora do ar"
    wording, because that's the one case where it's actually true (a real
    HTTP error or connection failure with no anti-bot signal detected)."""
    if status == WebsiteStatus.BLOCKED:
        return [_BLOCKED_PROBLEM]
    if status == WebsiteStatus.TIMEOUT:
        return [_TIMEOUT_PROBLEM]
    if status == WebsiteStatus.WEBSITE_NOT_FOUND:
        return [_WEBSITE_NOT_FOUND_PROBLEM]
    if status == WebsiteStatus.JS_REQUIRED:
        return [_JS_REQUIRED_PROBLEM]

    if not pages:
        return ["Site não pôde ser acessado (nenhuma página respondeu)."]

    homepage = next((p for p in pages if p.page_type == PageType.HOMEPAGE), pages[0])
    homepage_ok = homepage.http_status is not None and homepage.http_status < 400

    if not homepage_ok:
        if homepage.http_status:
            return [
                f"Site fora do ar ou com erro (HTTP {homepage.http_status}) — "
                "quem tenta visitar não consegue."
            ]
        return ["Site fora do ar ou inacessível — quem tenta visitar não consegue."]

    problems: list[str] = []

    if not homepage.has_viewport_meta:
        problems.append(_VIEWPORT_PROBLEM)

    has_any_contact_method = any(
        p.has_contact_form or p.has_phone_link or p.has_email_link or p.has_whatsapp_link
        for p in pages
    ) or any(p.page_type == PageType.CONTACT for p in pages)
    if not has_any_contact_method:
        problems.append(_NO_CONTACT_PROBLEM)

    if not homepage.has_nav:
        problems.append(_NO_NAV_PROBLEM)

    if not any(p.page_type == PageType.SERVICES for p in pages):
        problems.append(_NO_SERVICES_PAGE_PROBLEM)

    if not homepage.title or not homepage.meta_description:
        problems.append(_MISSING_TITLE_OR_DESCRIPTION_PROBLEM)

    if homepage.word_count < 100:
        problems.append(_THIN_CONTENT_PROBLEM)

    return problems
