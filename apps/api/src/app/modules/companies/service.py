import enum
import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from difflib import SequenceMatcher
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.companies.enums import CompanyStatus
from app.modules.companies.models import Company, CompanySource

# --- normalization ---------------------------------------------------------
# Pure functions, no DB — unit tested directly (spec section 68: normalization
# belongs in unit tests).


def normalize_name(name: str) -> str:
    """Lowercase, strip accents/punctuation, collapse whitespace — good enough
    for exact-match comparison, not for the fuzzy LOW-confidence tier (see
    name_similarity)."""
    decomposed = unicodedata.normalize("NFKD", name)
    without_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    lowered = without_accents.lower()
    alnum_only = re.sub(r"[^a-z0-9\s]", " ", lowered)
    return re.sub(r"\s+", " ", alnum_only).strip()


def normalize_phone(phone: str | None) -> str | None:
    """Digits only, keeping a leading '+' if present. Doesn't validate that
    the result is a plausible phone number — that's the caller's job if it
    matters; this only makes two representations of the same number compare
    equal (spec section 27's phone-match tier)."""
    if not phone:
        return None
    has_plus = phone.strip().startswith("+")
    digits = re.sub(r"\D", "", phone)
    if not digits:
        return None
    return f"+{digits}" if has_plus else digits


def extract_domain(website: str | None) -> str | None:
    """example.com from https://www.example.com/path — used for the
    domain-match HIGH-confidence tier. Returns None for anything that doesn't
    parse to a real host, rather than guessing."""
    if not website:
        return None
    candidate = website if "://" in website else f"//{website}"
    host = urlparse(candidate).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host or None


def name_similarity(a: str, b: str) -> float:
    """0..1. Only used for the LOW-confidence tier — never drives an
    auto-merge on its own (spec section 27: 'não realizar merge automático
    com baixa confiança')."""
    return SequenceMatcher(None, a, b).ratio()


# --- identity resolution -----------------------------------------------


class MatchConfidence(enum.IntEnum):
    """Ordered so `max(confidences)` picks the strongest match."""

    NONE = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3


@dataclass
class NormalizedRawCompany:
    provider: str
    external_id: str | None
    name: str
    segment: str
    city: str
    state: str
    country: str
    address: str | None = None
    phone: str | None = None
    website: str | None = None
    # Real, observed signal — not an inference: Apify's Google Maps data
    # reports this directly (permanentlyClosed). OSM has no equivalent, so
    # this always defaults False there. Drives upsert_company_from_raw
    # marking the company INVALID (see spec section 15's original ask: only
    # show places that are still active).
    permanently_closed: bool = False
    raw_data: dict = field(default_factory=dict)

    @property
    def normalized_name(self) -> str:
        return normalize_name(self.name)

    @property
    def normalized_phone(self) -> str | None:
        return normalize_phone(self.phone)

    @property
    def domain(self) -> str | None:
        return extract_domain(self.website)


@dataclass
class ExistingCompanyRef:
    """Just enough of a Company (+ its known sources) to classify a match
    against — keeps classify_match a pure function independent of the ORM."""

    id: uuid.UUID
    normalized_name: str
    address: str | None
    phone: str | None
    website: str | None
    known_sources: frozenset[tuple[str, str]]  # {(provider, external_id)}

    @property
    def domain(self) -> str | None:
        return extract_domain(self.website)


_NAME_SIMILARITY_THRESHOLD = 0.85


def classify_match(existing: ExistingCompanyRef, raw: NormalizedRawCompany) -> MatchConfidence:
    if raw.external_id and (raw.provider, raw.external_id) in existing.known_sources:
        return MatchConfidence.HIGH
    if raw.domain and existing.domain and raw.domain == existing.domain:
        return MatchConfidence.HIGH
    if raw.normalized_phone and existing.phone and raw.normalized_phone == existing.phone:
        return MatchConfidence.HIGH

    # Note: there's no separate "same name + phone" MEDIUM tier here — any
    # phone match at all is already HIGH above, making that combination
    # unreachable. Only name+address remains as a genuinely distinct MEDIUM
    # signal (address alone isn't in the HIGH tier).
    same_name = raw.normalized_name == existing.normalized_name
    if same_name and raw.address and existing.address and raw.address == existing.address:
        return MatchConfidence.MEDIUM

    if (
        raw.address
        and existing.address
        and name_similarity(raw.normalized_name, existing.normalized_name)
        >= _NAME_SIMILARITY_THRESHOLD
    ):
        return MatchConfidence.LOW

    return MatchConfidence.NONE


# --- DB-touching orchestration -----------------------------------------


async def _fetch_candidates(
    db: AsyncSession, tenant_id: uuid.UUID, raw: NormalizedRawCompany
) -> list[Company]:
    """Bounded candidate set: same tenant + segment + city. At this project's
    scale (~30-35 companies per segment per campaign) that's small enough to
    classify pairwise in Python rather than needing fuzzy matching in SQL."""
    result = await db.execute(
        select(Company).where(
            Company.tenant_id == tenant_id,
            Company.segment == raw.segment,
            Company.city == raw.city,
        )
    )
    return list(result.scalars())


async def _existing_ref(db: AsyncSession, company: Company) -> ExistingCompanyRef:
    sources_result = await db.execute(
        select(CompanySource.provider, CompanySource.external_id).where(
            CompanySource.company_id == company.id
        )
    )
    known_sources = frozenset((row[0], row[1]) for row in sources_result.all())
    return ExistingCompanyRef(
        id=company.id,
        normalized_name=company.normalized_name,
        address=company.address,
        phone=company.phone,
        website=company.website,
        known_sources=known_sources,
    )


def merge_missing_fields(company: Company, raw: NormalizedRawCompany) -> list[str]:
    """Fills gaps on an already-matched company from a newly-seen duplicate
    record — e.g. OSM found the company with no phone, a later
    re-discovery (or a second provider) has one. Never overwrites a field
    that's already set: when two sources genuinely disagree, the existing
    canonical value stays and the raw record's own value is still preserved
    via CompanySource.data for audit (spec section 13) — "não sobrescreva
    cegamente". Returns which fields were actually filled, for logging.

    This was a real bug (found during the Apify integration audit): a HIGH-
    confidence match only ever recorded the new CompanySource and returned
    the existing company untouched — phone/website a later duplicate did
    have never made it onto the canonical Company row."""
    filled: list[str] = []
    if not company.phone and raw.normalized_phone:
        company.phone = raw.normalized_phone
        filled.append("phone")
    if not company.website and raw.website:
        company.website = raw.website
        filled.append("website")
    if not company.address and raw.address:
        company.address = raw.address
        filled.append("address")
    return filled


async def upsert_company_from_raw(
    db: AsyncSession, tenant_id: uuid.UUID, raw: NormalizedRawCompany
) -> tuple[Company, MatchConfidence]:
    """The core Discovery -> Company step. Returns the resulting company and
    the confidence that led to it (HIGH -> merged into an existing company;
    MEDIUM/LOW/NONE -> a new company was created, MEDIUM flagged for review).
    """
    candidates = await _fetch_candidates(db, tenant_id, raw)

    best_company: Company | None = None
    best_confidence = MatchConfidence.NONE
    for candidate in candidates:
        ref = await _existing_ref(db, candidate)
        confidence = classify_match(ref, raw)
        if confidence > best_confidence:
            best_confidence = confidence
            best_company = candidate

    if best_confidence == MatchConfidence.HIGH and best_company is not None:
        filled = merge_missing_fields(best_company, raw)
        closed_now = raw.permanently_closed and best_company.status != CompanyStatus.INVALID
        if closed_now:
            best_company.status = CompanyStatus.INVALID
        if filled or closed_now:
            await db.flush()
        await _record_source(db, tenant_id, best_company.id, raw)
        return best_company, best_confidence

    company = Company(
        tenant_id=tenant_id,
        name=raw.name,
        normalized_name=raw.normalized_name,
        segment=raw.segment,
        address=raw.address,
        city=raw.city,
        state=raw.state,
        country=raw.country,
        phone=raw.normalized_phone,
        website=raw.website,
        # A place a provider reports as permanently closed is discovered
        # already-invalid, not DISCOVERED-then-manually-corrected — real,
        # observed signal (Apify), not an inference (spec section 15/35).
        status=CompanyStatus.INVALID if raw.permanently_closed else CompanyStatus.DISCOVERED,
        needs_review=(best_confidence == MatchConfidence.MEDIUM),
    )
    db.add(company)
    await db.flush()
    await _record_source(db, tenant_id, company.id, raw)
    return company, best_confidence


async def _record_source(
    db: AsyncSession, tenant_id: uuid.UUID, company_id: uuid.UUID, raw: NormalizedRawCompany
) -> None:
    if not raw.external_id:
        return
    existing = await db.execute(
        select(CompanySource).where(
            CompanySource.tenant_id == tenant_id,
            CompanySource.provider == raw.provider,
            CompanySource.external_id == raw.external_id,
        )
    )
    if existing.scalar_one_or_none() is not None:
        return
    db.add(
        CompanySource(
            tenant_id=tenant_id,
            company_id=company_id,
            provider=raw.provider,
            external_id=raw.external_id,
            collected_at=_now(),
            data=raw.raw_data,
        )
    )
    await db.flush()


def _now() -> datetime:
    return datetime.now(UTC)


async def list_companies(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    segment: str | None = None,
    city: str | None = None,
    status: CompanyStatus | None = None,
) -> list[Company]:
    query = select(Company).where(Company.tenant_id == tenant_id)
    if segment is not None:
        query = query.where(Company.segment == segment)
    if city is not None:
        query = query.where(Company.city == city)
    if status is not None:
        query = query.where(Company.status == status)
    else:
        # Default view is "still worth contacting": hide companies a human
        # marked INVALID (e.g. confirmed closed — see update_company_status)
        # and DUPLICATE (merged into another record). Explicitly asking for
        # status=INVALID/DUPLICATE still works, this only changes the default.
        query = query.where(
            Company.status.notin_([CompanyStatus.INVALID, CompanyStatus.DUPLICATE])
        )
    query = query.order_by(Company.created_at.desc())
    result = await db.execute(query)
    return list(result.scalars())


async def get_company(
    db: AsyncSession, tenant_id: uuid.UUID, company_id: uuid.UUID
) -> Company | None:
    result = await db.execute(
        select(Company).where(Company.tenant_id == tenant_id, Company.id == company_id)
    )
    return result.scalar_one_or_none()


async def update_company(
    db: AsyncSession,
    company: Company,
    status: CompanyStatus | None = None,
    do_not_contact: bool | None = None,
) -> Company:
    """No transition-rule enforcement on `status` (unlike Campaign's state
    machine) — any status is reachable from any other. Both fields are
    typically human corrections (a closed business; a do-not-contact
    request), not pipeline-driven transitions, so there's no fixed sequence
    to validate."""
    if status is not None:
        company.status = status
    if do_not_contact is not None:
        company.do_not_contact = do_not_contact
    await db.flush()
    return company


async def list_sources(
    db: AsyncSession, tenant_id: uuid.UUID, company_id: uuid.UUID
) -> list[CompanySource]:
    result = await db.execute(
        select(CompanySource)
        .where(CompanySource.tenant_id == tenant_id, CompanySource.company_id == company_id)
        .order_by(CompanySource.collected_at)
    )
    return list(result.scalars())
