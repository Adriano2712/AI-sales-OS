from dataclasses import dataclass

from app.modules.companies.enums import CompanyStatus
from app.modules.opportunities.enums import (
    OpportunityClassification,
    OpportunityOutcome,
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


# --- Fase 7: Opportunity Score 2.0 -----------------------------------------
# Everything above (WEIGHTS/OpportunityComponents/compute_components/
# compute_opportunity_score) is the original 4-factor formula — kept exactly
# as-is (still unit tested, still the source of Opportunity.digital_gap/
# business_fit/need/commercial_signals, spec's own backward-compat columns).
# What follows blends in the signals every phase since Fase 3 deliberately
# deferred here: Evidence polarity, Google reviews (Fase 4), website
# quality/opportunity scores (Fase 5), service fit + buying potential
# (Fase 6) — plus penalties and a genuinely separate OPPORTUNITY_CONFIDENCE,
# both requested explicitly for this phase.

# Sums to 1.0 by construction, but compute_opportunity_score_v2 renormalizes
# over whatever's actually evaluated anyway — these don't need to stay
# exactly 1.0 if a campaign overrides some of them (see OpportunityWeights
# in opportunities/schemas.py).
DEFAULT_WEIGHTS_V2: dict[str, float] = {
    "digital_gap": 0.15,
    "business_fit": 0.15,
    "service_fit": 0.15,
    "need": 0.10,
    "commercial_signals": 0.10,
    "buying_potential": 0.15,
    "website_opportunity": 0.10,
    "customer_validation": 0.05,
    "evidence_signal_balance": 0.05,
}

# Fixed system-wide constants, not (yet) campaign-configurable — the master
# spec calls out per-campaign *weights* explicitly; penalties are a smaller,
# more universally-true set of "this isn't a fresh, workable opportunity"
# signals (spec's own negative examples: apparently-closed business,
# already-existing/already-contacted opportunity) that don't obviously vary
# by campaign the way factor importance does.
_PENALTY_INVALID_OR_DUPLICATE = 60.0
_PENALTY_DO_NOT_CONTACT = 30.0
_PENALTY_ALREADY_HAS_OUTCOME = 20.0


@dataclass
class OpportunityFactors:
    """The full Score 2.0 input set. Every field independently None-able —
    same renormalize-over-known-dimensions discipline as OpportunityComponents
    above, just with five more real sources blended in."""

    digital_gap: float | None
    business_fit: float | None
    service_fit: float | None
    need: float | None
    commercial_signals: float | None
    buying_potential: float | None
    website_opportunity: float | None
    customer_validation: float | None
    evidence_signal_balance: float | None


@dataclass
class OpportunityPenalty:
    points: float
    reasons: list[str]


def compute_opportunity_factors(
    business_fit_score: float | None,
    activity_score: float | None,
    need_score: float | None,
    service_fit_score: float | None,
    buying_potential_score: float | None,
    website_opportunity_score: float | None,
    has_google_reviews: bool,
    evidence_signal_balance: float | None,
) -> OpportunityFactors:
    """`customer_validation` is deliberately presence-only (100 when the
    company has real Google review data at all, None otherwise) — same
    design decision Fase 4 already made for the underlying evidence: a
    star rating's actual *value* is never judged here (no defensible,
    non-invented threshold exists for what counts as a "good enough"
    rating), only whether real third-party validation exists."""
    return OpportunityFactors(
        digital_gap=need_score,
        business_fit=business_fit_score,
        service_fit=service_fit_score,
        need=compute_need(need_score, activity_score),
        commercial_signals=activity_score,
        buying_potential=buying_potential_score,
        website_opportunity=website_opportunity_score,
        customer_validation=100.0 if has_google_reviews else None,
        evidence_signal_balance=evidence_signal_balance,
    )


def compute_opportunity_score_v2(
    factors: OpportunityFactors, weights: dict[str, float] | None = None
) -> float | None:
    """Same renormalize-over-known-dimensions pattern as every score in this
    project — a factor that couldn't be evaluated is simply excluded, never
    filled with a guess. `weights` (a campaign's override, see
    opportunities/schemas.py::OpportunityWeights) may specify only some
    factors; any not present fall back to DEFAULT_WEIGHTS_V2, not zero."""
    active = weights or DEFAULT_WEIGHTS_V2
    parts = [
        (factors.digital_gap, active.get("digital_gap", DEFAULT_WEIGHTS_V2["digital_gap"])),
        (factors.business_fit, active.get("business_fit", DEFAULT_WEIGHTS_V2["business_fit"])),
        (factors.service_fit, active.get("service_fit", DEFAULT_WEIGHTS_V2["service_fit"])),
        (factors.need, active.get("need", DEFAULT_WEIGHTS_V2["need"])),
        (
            factors.commercial_signals,
            active.get("commercial_signals", DEFAULT_WEIGHTS_V2["commercial_signals"]),
        ),
        (
            factors.buying_potential,
            active.get("buying_potential", DEFAULT_WEIGHTS_V2["buying_potential"]),
        ),
        (
            factors.website_opportunity,
            active.get("website_opportunity", DEFAULT_WEIGHTS_V2["website_opportunity"]),
        ),
        (
            factors.customer_validation,
            active.get("customer_validation", DEFAULT_WEIGHTS_V2["customer_validation"]),
        ),
        (
            factors.evidence_signal_balance,
            active.get("evidence_signal_balance", DEFAULT_WEIGHTS_V2["evidence_signal_balance"]),
        ),
    ]
    evaluated = [(score, weight) for score, weight in parts if score is not None and weight > 0]
    if not evaluated:
        return None
    total_weight = sum(weight for _, weight in evaluated)
    weighted_sum = sum(score * weight for score, weight in evaluated)
    return round(weighted_sum / total_weight, 1)


def compute_penalties(
    company_status: CompanyStatus,
    do_not_contact: bool,
    existing_outcome: OpportunityOutcome | None,
) -> OpportunityPenalty:
    """Subtracted from the raw weighted score, never blended into it — a
    penalty reflects "this isn't a fresh, workable opportunity right now",
    a different question from "how good would this opportunity be if it
    were workable" (spec's own negative examples: apparently-closed
    business, already-existing/contacted opportunity)."""
    points = 0.0
    reasons: list[str] = []
    if company_status in (CompanyStatus.INVALID, CompanyStatus.DUPLICATE):
        points += _PENALTY_INVALID_OR_DUPLICATE
        reasons.append(f"Company status is {company_status.value}")
    if do_not_contact:
        points += _PENALTY_DO_NOT_CONTACT
        reasons.append("Company is marked do-not-contact")
    if existing_outcome is not None:
        points += _PENALTY_ALREADY_HAS_OUTCOME
        reasons.append(f"Opportunity already has a tracked outcome ({existing_outcome.value})")
    return OpportunityPenalty(points=points, reasons=reasons)


def apply_penalty(raw_score: float | None, penalty_points: float) -> float | None:
    """Clipped at 0 — a penalty can zero out a score, never invert it."""
    if raw_score is None:
        return None
    return round(max(0.0, raw_score - penalty_points), 1)


def compute_opportunity_confidence(
    business_analysis_confidence: float | None, factors: OpportunityFactors
) -> float | None:
    """OPPORTUNITY_CONFIDENCE (spec: kept separate from opportunity_score
    itself, same "score != confidence" rule as BusinessAnalysis/
    WebsiteAnalysis). Blends two independent questions: how confident was
    the AI Analyst in its own judgment (business_analysis_confidence), and
    how complete is the picture this specific score was built from (the
    fraction of the 9 Score-2.0 factors that were actually evaluable). A
    score built from 2 of 9 known factors deserves lower confidence than an
    identical-looking score built from 8 of 9, even with the same AI
    confidence input — this makes that distinction real instead of hiding
    it behind a single pass-through number."""
    if business_analysis_confidence is None:
        return None
    values = (
        factors.digital_gap,
        factors.business_fit,
        factors.service_fit,
        factors.need,
        factors.commercial_signals,
        factors.buying_potential,
        factors.website_opportunity,
        factors.customer_validation,
        factors.evidence_signal_balance,
    )
    completeness = sum(1 for v in values if v is not None) / len(values)
    return round(business_analysis_confidence * completeness, 1)


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
