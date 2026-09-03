from dataclasses import dataclass

from app.modules.opportunities.enums import (
    OpportunityClassification,
    OpportunityStatus,
    OpportunityType,
)

# Spec section 40: none of the 4 components is spec'd as more important than
# another (only Business Analysis's own weights, spec section 33, are given
# numerically) — equal weight by default, configurable like Fase 5's WEIGHTS.
# Confidence is deliberately excluded from this weighting (spec section 42:
# score != confidence) — it rides along as its own field, never blended in.
WEIGHTS: dict[str, float] = {
    "digital_gap": 0.25,
    "business_fit": 0.25,
    "need": 0.25,
    "commercial_signals": 0.25,
}

# Spec section 41 — thresholds configurable, these are the defaults.
_CLASSIFICATION_THRESHOLDS: list[tuple[float, OpportunityClassification]] = [
    (90.0, OpportunityClassification.HIGH),
    (75.0, OpportunityClassification.GOOD),
    (60.0, OpportunityClassification.REVIEW),
]

# Below this, there's no real measured evidence that the "website" dimension
# is the actual gap — see determine_opportunity_type.
_LOW_DIGITAL_MATURITY_THRESHOLD = 50.0


@dataclass
class OpportunityComponents:
    digital_gap: float | None
    business_fit: float | None
    need: float | None
    commercial_signals: float | None


def compute_need(need_score: float | None, activity_score: float | None) -> float | None:
    """Average of two independent "this business needs help" signals: low
    digital maturity (need_score, already 100 - digital_maturity_score from
    Fase 5) and low visible commercial activity (activity_score inverted).
    Averages over whichever is actually known rather than requiring both."""
    inverted_activity = 100.0 - activity_score if activity_score is not None else None
    parts = [p for p in (need_score, inverted_activity) if p is not None]
    if not parts:
        return None
    return round(sum(parts) / len(parts), 1)


def compute_components(
    business_fit_score: float | None,
    activity_score: float | None,
    need_score: float | None,
) -> OpportunityComponents:
    return OpportunityComponents(
        digital_gap=need_score,
        business_fit=business_fit_score,
        need=compute_need(need_score, activity_score),
        commercial_signals=activity_score,
    )


def compute_opportunity_score(components: OpportunityComponents) -> float | None:
    """Same renormalize-over-known-dimensions pattern as Fase 4/5's scores —
    never fills a missing component with a guess (spec section 35)."""
    parts = [
        (components.digital_gap, WEIGHTS["digital_gap"]),
        (components.business_fit, WEIGHTS["business_fit"]),
        (components.need, WEIGHTS["need"]),
        (components.commercial_signals, WEIGHTS["commercial_signals"]),
    ]
    evaluated = [(score, weight) for score, weight in parts if score is not None]
    if not evaluated:
        return None

    total_weight = sum(weight for _, weight in evaluated)
    weighted_sum = sum(score * weight for score, weight in evaluated)
    return round(weighted_sum / total_weight, 1)


def classify_opportunity(opportunity_score: float | None) -> OpportunityClassification | None:
    if opportunity_score is None:
        return None
    for threshold, label in _CLASSIFICATION_THRESHOLDS:
        if opportunity_score >= threshold:
            return label
    return OpportunityClassification.LOW


def determine_opportunity_type(digital_maturity_score: float | None) -> OpportunityType:
    """Only classifies WEBSITE when there's real measured evidence for it
    (a low digital_maturity_score from Fase 4/5). Every other spec section 44
    type (E_COMMERCE/AUTOMATION/INTERNAL_SYSTEM/INTEGRATION/DIGITAL_PRESENCE)
    would need signals this pipeline doesn't collect yet — guessing one would
    violate spec section 35's anti-hallucination rule, so OTHER is the honest
    fallback rather than an invented classification."""
    if (
        digital_maturity_score is not None
        and digital_maturity_score < _LOW_DIGITAL_MATURITY_THRESHOLD
    ):
        return OpportunityType.WEBSITE
    return OpportunityType.OTHER


def derive_potential_solution(
    opportunity_type: OpportunityType, has_website: bool
) -> str | None:
    """Templated, not invented — only fires when determine_opportunity_type
    found real evidence (WEBSITE). Everything else stays None/UNKNOWN rather
    than guessing a solution with no supporting signal."""
    if opportunity_type is not OpportunityType.WEBSITE:
        return None
    if not has_website:
        return "Criar um site institucional/comercial — nenhuma presença digital própria foi encontrada."
    return "Modernizar o site existente — pontuação digital baixa nas dimensões avaliadas."


# Spec section 46's dashboard field, kept a pure function of `status` rather
# than a stored column — nothing here needs the AI Analyst or an invented
# recommendation (spec section 35), it's a direct mapping of "what does a
# human do next given where this opportunity is in its own status machine."
_NEXT_ACTION_BY_STATUS: dict[OpportunityStatus, str] = {
    OpportunityStatus.OPEN: "Revisar oportunidade",
    OpportunityStatus.REVIEWING: "Decidir: aprovar ou rejeitar",
    OpportunityStatus.APPROVED: "Aguardando SDR Assistido (Fase 8)",
    OpportunityStatus.REJECTED: "Nenhuma ação — rejeitada",
    OpportunityStatus.ARCHIVED: "Nenhuma ação — arquivada",
}


def derive_next_action(status: OpportunityStatus) -> str:
    return _NEXT_ACTION_BY_STATUS[status]
