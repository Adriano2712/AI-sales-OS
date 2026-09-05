import uuid

import pytest

from app.modules.evidence.enums import EvidenceCategory, EvidenceConfidence, EvidencePolarity
from app.modules.evidence.service import InvalidEvidencePolarity, get_or_create_evidence


@pytest.mark.asyncio
async def test_unknown_confidence_with_non_unknown_polarity_is_rejected():
    """The Opportunity Signal's one absolute rule, enforced in code: absence
    of evidence can never be recorded as a positive or negative signal.
    Raises before ever touching the database — `db` is never used here."""
    for bad_polarity in (EvidencePolarity.POSITIVE, EvidencePolarity.NEGATIVE, EvidencePolarity.NEUTRAL):
        with pytest.raises(InvalidEvidencePolarity):
            await get_or_create_evidence(
                db=None,  # type: ignore[arg-type]
                tenant_id=uuid.uuid4(),
                company_id=uuid.uuid4(),
                claim="No public evidence of a phone was found",
                source="test",
                confidence=EvidenceConfidence.UNKNOWN,
                polarity=bad_polarity,
                category=EvidenceCategory.CONTACTABILITY,
            )
