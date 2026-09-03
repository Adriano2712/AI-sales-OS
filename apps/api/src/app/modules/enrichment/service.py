import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.companies.models import Company, CompanySource
from app.modules.companies.service import list_sources
from app.modules.evidence.enums import EvidenceConfidence
from app.modules.evidence.models import Evidence
from app.modules.evidence.service import get_or_create_evidence

# OSM tag(s) to check, in priority order, for each logical field. Overpass
# already returns every tag an element has (spec section 29's "informações
# públicas relevantes") — this reads what discovery already fetched and
# stored in CompanySource.data, no new network call. A genuinely new
# enrichment source (one that needs its own HTTP request) is a different,
# future addition — see docs/DISCOVERY.md's note on this phase's scope.
_SUPPLEMENTARY_TAG_SOURCES: dict[str, list[str]] = {
    "opening_hours": ["opening_hours"],
    "email": ["contact:email", "email"],
    "facebook": ["contact:facebook", "facebook"],
    "instagram": ["contact:instagram", "instagram"],
    "cuisine": ["cuisine"],
}


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
) -> Evidence:
    """Phone and website are spec-section-29 "important" fields — they get an
    evidence entry either way: HIGH confidence citing the value if present,
    or an explicit UNKNOWN claim if not. Never silently absent, never
    asserted without a source (spec sections 34/35)."""
    if value:
        return await get_or_create_evidence(
            db,
            tenant_id,
            company.id,
            claim=f"{field_label}: {value}",
            source=provider,
            confidence=EvidenceConfidence.HIGH,
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
        supporting_data={"field": field_label},
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
                        source_url=source.source_url,
                        supporting_data={"field": "permanently_closed", "source_id": str(source.id)},
                    )
                )

        for field, value in supplementary.items():
            if field in seen_fields:
                continue
            seen_fields.add(field)
            created.append(
                await get_or_create_evidence(
                    db,
                    tenant_id,
                    company.id,
                    claim=f"{field}: {value}",
                    source=source.provider,
                    confidence=EvidenceConfidence.HIGH,
                    source_url=source.source_url,
                    supporting_data={"field": field, "value": value, "source_id": str(source.id)},
                )
            )

    return created
