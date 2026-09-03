from dataclasses import dataclass

# Spec section 33.
WEIGHTS: dict[str, float] = {
    "business_fit": 0.20,
    "activity": 0.20,
    "digital_maturity": 0.20,
    "need": 0.25,
    "compatibility": 0.15,
}


@dataclass
class DeterministicScores:
    """activity/digital_maturity/need computed here without any AI call —
    they're directly derivable from data already collected in earlier
    phases (spec section 39: prefer a deterministic rule over an AI call
    when one genuinely answers the question)."""

    activity_score: float | None
    digital_maturity_score: float | None
    need_score: float | None


def compute_digital_maturity_score(
    has_website: bool, website_digital_score: float | None
) -> float | None:
    """No website at all is itself a measured fact (0), not a guess. A
    website that exists but hasn't been analyzed yet is genuinely unknown —
    stays None rather than assuming either extreme."""
    if not has_website:
        return 0.0
    return website_digital_score


def compute_activity_score(
    has_phone: bool, has_website: bool, has_opening_hours_evidence: bool
) -> float:
    """Fraction of independent "this business is actually operating" signals
    we found evidence for. Always evaluable (unlike the website-derived
    scores) — absence of all three signals is itself a real, measurable
    activity_score of 0, not an unknown."""
    signals = [has_phone, has_website, has_opening_hours_evidence]
    return round(100.0 * sum(signals) / len(signals), 1)


def compute_need_score(digital_maturity_score: float | None) -> float | None:
    """Inverse of digital maturity — low digital maturity is itself the
    evidence for high need, not a separate judgment call. Stays None when
    digital_maturity_score is None (nothing to invert)."""
    if digital_maturity_score is None:
        return None
    return round(100.0 - digital_maturity_score, 1)


def compute_deterministic_scores(
    has_website: bool,
    website_digital_score: float | None,
    has_phone: bool,
    has_opening_hours_evidence: bool,
) -> DeterministicScores:
    digital_maturity = compute_digital_maturity_score(has_website, website_digital_score)
    return DeterministicScores(
        activity_score=compute_activity_score(has_phone, has_website, has_opening_hours_evidence),
        digital_maturity_score=digital_maturity,
        need_score=compute_need_score(digital_maturity),
    )


def compute_overall_score(
    business_fit_score: float | None,
    activity_score: float | None,
    digital_maturity_score: float | None,
    need_score: float | None,
    compatibility_score: float | None,
) -> float | None:
    """Same renormalize-over-evaluated-dimensions pattern as Fase 4's
    digital_score — never fills a gap with a guess."""
    parts = [
        (business_fit_score, WEIGHTS["business_fit"]),
        (activity_score, WEIGHTS["activity"]),
        (digital_maturity_score, WEIGHTS["digital_maturity"]),
        (need_score, WEIGHTS["need"]),
        (compatibility_score, WEIGHTS["compatibility"]),
    ]
    evaluated = [(score, weight) for score, weight in parts if score is not None]
    if not evaluated:
        return None

    total_weight = sum(weight for _, weight in evaluated)
    weighted_sum = sum(score * weight for score, weight in evaluated)
    return round(weighted_sum / total_weight, 1)
