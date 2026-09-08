import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.companies.models import Company, CompanySource
from app.modules.companies.service import list_sources
from app.modules.evidence.enums import EvidenceCategory, EvidenceConfidence, EvidencePolarity
from app.modules.evidence.models import Evidence
from app.modules.evidence.service import get_or_create_evidence

# Opportunity Signal classification (Fase 3) for each supplementary field —
# kept as one explicit, reviewable table rather than inline judgment calls
# scattered through the loop below. A field found here is real, public
# information (never a guess), so it's never UNKNOWN; polarity reflects what
# it means for *our* opportunity, not a judgment on the business (see
# EvidencePolarity's docstring). Any field not listed here (e.g. a future
# addition to the extraction dicts above) safely defaults to
# NEUTRAL/OTHER rather than crashing — but should get a real entry here.
_SUPPLEMENTARY_FIELD_SIGNAL: dict[str, tuple[EvidencePolarity, EvidenceCategory]] = {
    "opening_hours": (EvidencePolarity.NEUTRAL, EvidenceCategory.BUSINESS_STATUS),
    "facebook": (EvidencePolarity.POSITIVE, EvidenceCategory.SOCIAL_PRESENCE),
    "cuisine": (EvidencePolarity.NEUTRAL, EvidenceCategory.OTHER),
    "category": (EvidencePolarity.NEUTRAL, EvidenceCategory.OTHER),
}

# OSM tag(s) to check, in priority order, for each logical field. Overpass
# already returns every tag an element has (spec section 29's "informações
# públicas relevantes") — this reads what discovery already fetched and
# stored in CompanySource.data, no new network call. A genuinely new
# enrichment source (one that needs its own HTTP request) is a different,
# future addition — see docs/DISCOVERY.md's note on this phase's scope.
_SUPPLEMENTARY_TAG_SOURCES: dict[str, list[str]] = {
    "opening_hours": ["opening_hours"],
    "facebook": ["contact:facebook", "facebook"],
    "cuisine": ["cuisine"],
}
# instagram and (as of the automation-planning session) email are
# deliberately absent here: both are now core fields — read from
# company.instagram_url / company.email (set at discovery time, see
# discovery/providers/overpass.py, and — for email — also filled from the
# company's own website during website analysis) and always get an
# evidence row either way via _record_core_field_evidence, the same
# treatment as phone/website. The master spec explicitly lists "Instagram
# not found" as an UNKNOWN example — the old supplementary path silently
# emitted no evidence at all when absent, which doesn't satisfy that.


def extract_supplementary_fields(osm_tags: dict[str, str]) -> dict[str, str]:
    """Pure function — unit tested directly. Returns only fields actually
    present; never fabricates a value for a missing tag."""
    found: dict[str, str] = {}
    for field, tag_keys in _SUPPLEMENTARY_TAG_SOURCES.items():
        for key in tag_keys:
            value = osm_tags.get(key)
            if value:
                found[field] = value
                break
    return found


def extract_apify_supplementary_fields(apify_place: dict) -> dict[str, str]:
    """Apify-side equivalent of extract_supplementary_fields, reading only
    fields actually confirmed present in a real run against this project's
    Apify account (see docs/DISCOVERY.md) — never a guessed field name.
    permanentlyClosed/temporarilyClosed are handled separately in
    enrich_company (they change status, not just add evidence)."""
    found: dict[str, str] = {}
    opening_hours = apify_place.get("openingHours")
    if opening_hours:
        formatted = "; ".join(
            f"{entry['day']}: {entry['hours']}"
            for entry in opening_hours
            if entry.get("day") and entry.get("hours")
        )
        if formatted:
            found["opening_hours"] = formatted
    category = apify_place.get("categoryName")
    if category:
        found["category"] = category
    return found


async def _record_core_field_evidence(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    company: Company,
    field_label: str,
    value: str | None,
    provider: str,
    source_url: str | None,
    category: EvidenceCategory = EvidenceCategory.CONTACTABILITY,
) -> Evidence:
    """Phone, website and (Fase 4) instagram are "important" fields that get
    an evidence entry either way: HIGH confidence citing the value if
    present, or an explicit UNKNOWN claim if not. Never silently absent,
    never asserted without a source (spec sections 34/35)."""
    if value:
        return await get_or_create_evidence(
            db,
            tenant_id,
            company.id,
            claim=f"{field_label}: {value}",
            source=provider,
            confidence=EvidenceConfidence.HIGH,
            # Real contact/social presence found — matches the spec's own
            # "contato disponível" / "presença social ativa" positive
            # examples directly.
            polarity=EvidencePolarity.POSITIVE,
            category=category,
            source_url=source_url,
            supporting_data={"field": field_label, "value": value},
        )
    return await get_or_create_evidence(
        db,
        tenant_id,
        company.id,
        claim=f"No public evidence of a {field_label} was found",
        source=provider,
        confidence=EvidenceConfidence.UNKNOWN,
        # Absolute rule: absence of a phone/website/instagram is UNKNOWN,
        # never a negative signal — maybe they just don't publish it.
        polarity=EvidencePolarity.UNKNOWN,
        category=category,
        supporting_data={"field": field_label},
    )


async def _record_google_reviews_evidence(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    company: Company,
    provider: str,
    source_url: str | None,
) -> Evidence:
    """Google Review Intelligence (Fase 4). rating/review_count only ever
    come from a real Apify Google Maps result (see companies/service.py) —
    never invented. Presence is the signal recorded here (a real, discoverable,
    reviewed business — CUSTOMER_VALIDATION), not a judgment on the rating's
    *value* (a 2-star vs 5-star business isn't scored differently yet — that
    kind of weighting belongs to Opportunity Score 2.0, a later phase, not to
    evidence capture). Absence (not found on Google Maps, or only discovered
    via Overpass which has no rating data) is UNKNOWN, never negative."""
    if company.google_rating is not None:
        claim = f"Google rating: {company.google_rating}"
        if company.google_review_count is not None:
            claim += f" ({company.google_review_count} reviews)"
        return await get_or_create_evidence(
            db,
            tenant_id,
            company.id,
            claim=claim,
            source=provider,
            confidence=EvidenceConfidence.HIGH,
            polarity=EvidencePolarity.POSITIVE,
            category=EvidenceCategory.CUSTOMER_VALIDATION,
            source_url=source_url,
            supporting_data={
                "field": "google_reviews",
                "rating": company.google_rating,
                "review_count": company.google_review_count,
            },
        )
    return await get_or_create_evidence(
        db,
        tenant_id,
        company.id,
        claim="No Google rating/review data was found",
        source=provider,
        confidence=EvidenceConfidence.UNKNOWN,
        polarity=EvidencePolarity.UNKNOWN,
        category=EvidenceCategory.CUSTOMER_VALIDATION,
        supporting_data={"field": "google_reviews"},
    )


async def enrich_company(
    db: AsyncSession, tenant_id: uuid.UUID, company: Company
) -> list[Evidence]:
    sources = await list_sources(db, tenant_id, company.id)
    primary_source: CompanySource | None = sources[0] if sources else None
    provider = primary_source.provider if primary_source else "unknown"
    source_url = primary_source.source_url if primary_source else None

    created = [
        await _record_core_field_evidence(
            db, tenant_id, company, "phone", company.phone, provider, source_url
        ),
        await _record_core_field_evidence(
            db, tenant_id, company, "website", company.website, provider, source_url
        ),
        await _record_core_field_evidence(
            db,
            tenant_id,
            company,
            "instagram",
            company.instagram_url,
            provider,
            source_url,
            category=EvidenceCategory.SOCIAL_PRESENCE,
        ),
        # Real (not yet always known) at this point: only OSM's own
        # contact:email/email tag can have filled this by discovery time —
        # the other real source (the company's own website) hasn't been
        # fetched yet at all (website_analysis runs later, chained after
        # this). An UNKNOWN claim recorded here is an honest snapshot of
        # what was known when discovery finished, not a final answer — see
        # website_analysis's own email extraction for the distinct,
        # later-recorded claim when a site provides one.
        await _record_core_field_evidence(
            db, tenant_id, company, "email", company.email, provider, source_url
        ),
        await _record_google_reviews_evidence(db, tenant_id, company, provider, source_url),
    ]

    seen_fields: set[str] = set()
    for source in sources:
        supplementary: dict[str, str] = {}
        osm_tags = source.data.get("osm_tags", {})
        if osm_tags:
            supplementary.update(extract_supplementary_fields(osm_tags))

        apify_place = source.data.get("apify_place", {})
        if apify_place:
            supplementary.update(extract_apify_supplementary_fields(apify_place))
            if apify_place.get("permanentlyClosed"):
                created.append(
                    await get_or_create_evidence(
                        db,
                        tenant_id,
                        company.id,
                        claim="Google Maps indica que este local está permanentemente fechado",
                        source=source.provider,
                        confidence=EvidenceConfidence.HIGH,
                        # Matches the spec's own "negócio aparentemente
                        # encerrado" negative example directly.
                        polarity=EvidencePolarity.NEGATIVE,
                        category=EvidenceCategory.BUSINESS_STATUS,
                        source_url=source.source_url,
                        supporting_data={"field": "permanently_closed", "source_id": str(source.id)},
                    )
                )

        for field, value in supplementary.items():
            if field in seen_fields:
                continue
            seen_fields.add(field)
            polarity, category = _SUPPLEMENTARY_FIELD_SIGNAL.get(
                field, (EvidencePolarity.NEUTRAL, EvidenceCategory.OTHER)
            )
            created.append(
                await get_or_create_evidence(
                    db,
                    tenant_id,
                    company.id,
                    claim=f"{field}: {value}",
                    source=source.provider,
                    confidence=EvidenceConfidence.HIGH,
                    polarity=polarity,
                    category=category,
                    source_url=source.source_url,
                    supporting_data={"field": field, "value": value, "source_id": str(source.id)},
                )
            )

    return created
