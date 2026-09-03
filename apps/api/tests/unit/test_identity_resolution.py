import uuid

from app.modules.companies.service import (
    ExistingCompanyRef,
    MatchConfidence,
    NormalizedRawCompany,
    classify_match,
)


def _existing(**overrides) -> ExistingCompanyRef:
    defaults = dict(
        id=uuid.uuid4(),
        normalized_name="restaurante sao joao",
        address="Rua A 100",
        phone="1532314455",
        website="https://example.com",
        known_sources=frozenset(),
    )
    defaults.update(overrides)
    return ExistingCompanyRef(**defaults)


def _raw(**overrides) -> NormalizedRawCompany:
    defaults = dict(
        provider="overpass",
        external_id="node/123",
        name="Restaurante São João",
        segment="restaurants",
        city="Sorocaba",
        state="SP",
        country="BR",
        address="Rua A 100",
        phone="(15) 3231-4455",
        website="https://example.com",
    )
    defaults.update(overrides)
    return NormalizedRawCompany(**defaults)


def test_known_source_is_high_confidence():
    existing = _existing(known_sources=frozenset({("overpass", "node/123")}))
    raw = _raw(website=None, phone=None, address=None)  # only the source matches
    assert classify_match(existing, raw) == MatchConfidence.HIGH


def test_matching_domain_is_high_confidence():
    existing = _existing(phone=None, address=None, website="https://acme.com")
    raw = _raw(external_id=None, phone=None, address=None, website="https://www.acme.com/menu")
    assert classify_match(existing, raw) == MatchConfidence.HIGH


def test_matching_phone_is_high_confidence():
    existing = _existing(website=None, address=None, phone="1532314455")
    raw = _raw(external_id=None, website=None, address=None, phone="15 3231-4455")
    assert classify_match(existing, raw) == MatchConfidence.HIGH


def test_same_name_and_address_is_medium_confidence():
    existing = _existing(phone=None, website=None, address="Rua A 100")
    raw = _raw(external_id=None, phone=None, website=None, address="Rua A 100")
    assert classify_match(existing, raw) == MatchConfidence.MEDIUM


def test_phone_match_is_high_confidence_even_with_a_different_name():
    """Phone alone is in the HIGH tier (spec section 27) — it doesn't need the
    name to agree too. This also means "name + phone" can never surface as a
    separate MEDIUM signal: any phone match is already decisive on its own."""
    existing = _existing(
        normalized_name="restaurante sao joao", address=None, website=None, phone="1532314455"
    )
    raw = _raw(
        name="Completely Different Name",
        external_id=None,
        address=None,
        website=None,
        phone="1532314455",
    )
    assert classify_match(existing, raw) == MatchConfidence.HIGH


def test_similar_name_and_same_address_is_low_confidence_not_medium():
    existing = _existing(
        normalized_name="restaurante sao joao", phone=None, website=None, address="Rua A 100"
    )
    raw = _raw(
        name="Restaurante Sao Joao Ltda",  # similar, not identical after normalization
        external_id=None,
        phone=None,
        website=None,
        address="Rua A 100",
    )
    assert classify_match(existing, raw) == MatchConfidence.LOW


def test_unrelated_companies_do_not_match():
    existing = _existing(
        normalized_name="clinica saude total",
        address="Av B 200",
        phone="1533334444",
        website="https://clinicasaude.com",
    )
    raw = _raw(
        name="Pizzaria do Bairro",
        external_id=None,
        address="Rua C 300",
        phone="1599998888",
        website="https://pizzariadobairro.com",
    )
    assert classify_match(existing, raw) == MatchConfidence.NONE


def test_same_name_alone_without_address_or_phone_overlap_does_not_match():
    """Name matching alone is never enough — spec section 27 requires it paired
    with address for even MEDIUM confidence. Website is explicitly nulled on
    both sides here too, since a shared domain would independently trigger
    HIGH regardless of name."""
    existing = _existing(
        normalized_name="restaurante sao joao", address=None, phone=None, website=None
    )
    raw = _raw(
        name="Restaurante São João", external_id=None, address=None, phone=None, website=None
    )
    assert classify_match(existing, raw) == MatchConfidence.NONE
