from app.modules.companies.models import Company
from app.modules.companies.service import NormalizedRawCompany, merge_missing_fields


def _company(**overrides) -> Company:
    defaults = dict(
        phone=None,
        website=None,
        address=None,
        google_place_id=None,
        google_rating=None,
        google_review_count=None,
        instagram_url=None,
        email=None,
    )
    defaults.update(overrides)
    return Company(**defaults)


def _raw(**overrides) -> NormalizedRawCompany:
    defaults = dict(
        provider="overpass",
        external_id="node/123",
        name="Restaurante X",
        segment="restaurants",
        city="Sorocaba",
        state="SP",
        country="BR",
    )
    defaults.update(overrides)
    return NormalizedRawCompany(**defaults)


def test_fills_phone_when_company_has_none():
    company = _company(phone=None)
    raw = _raw(phone="(15) 99999-9999")
    filled = merge_missing_fields(company, raw)
    assert filled == ["phone"]
    assert company.phone == "15999999999"  # normalize_phone strips formatting


def test_fills_website_when_company_has_none():
    company = _company(website=None)
    raw = _raw(website="https://restaurantex.com.br")
    filled = merge_missing_fields(company, raw)
    assert filled == ["website"]
    assert company.website == "https://restaurantex.com.br"


def test_fills_address_when_company_has_none():
    company = _company(address=None)
    raw = _raw(address="Rua X 100")
    filled = merge_missing_fields(company, raw)
    assert filled == ["address"]
    assert company.address == "Rua X 100"


def test_fills_all_three_at_once():
    company = _company(phone=None, website=None, address=None)
    raw = _raw(phone="15999999999", website="https://x.com", address="Rua X")
    filled = merge_missing_fields(company, raw)
    assert set(filled) == {"phone", "website", "address"}


def test_never_overwrites_an_existing_value():
    """Two sources disagreeing must not silently clobber the canonical
    value (spec: "não sobrescreva cegamente") — the raw record's own value
    is still preserved separately via CompanySource, this function's job is
    only to fill genuine gaps."""
    company = _company(phone="1533330000", website="https://original.com", address="Rua Original")
    raw = _raw(phone="1544440000", website="https://different.com", address="Rua Diferente")
    filled = merge_missing_fields(company, raw)
    assert filled == []
    assert company.phone == "1533330000"
    assert company.website == "https://original.com"
    assert company.address == "Rua Original"


def test_noop_when_raw_has_nothing_new():
    company = _company(phone=None, website=None, address=None)
    raw = _raw(phone=None, website=None, address=None)
    filled = merge_missing_fields(company, raw)
    assert filled == []


def test_fills_google_review_fields_when_company_has_none():
    company = _company()
    raw = _raw(google_place_id="ChIJabc123", google_rating=4.5, google_review_count=200)
    filled = merge_missing_fields(company, raw)
    assert set(filled) == {"google_place_id", "google_rating", "google_review_count"}
    assert company.google_place_id == "ChIJabc123"
    assert company.google_rating == 4.5
    assert company.google_review_count == 200


def test_fills_instagram_when_company_has_none():
    company = _company()
    raw = _raw(instagram="https://instagram.com/restaurantex")
    filled = merge_missing_fields(company, raw)
    assert filled == ["instagram_url"]
    assert company.instagram_url == "https://instagram.com/restaurantex"


def test_fills_email_when_company_has_none():
    """Real gap found during the automation-planning session:
    `Company.email` existed but nothing ever wrote to it -- now filled the
    same way phone/website/instagram already were."""
    company = _company()
    raw = _raw(email="contato@restaurantex.com.br")
    filled = merge_missing_fields(company, raw)
    assert filled == ["email"]
    assert company.email == "contato@restaurantex.com.br"


def test_never_overwrites_an_existing_email():
    company = _company(email="original@restaurantex.com.br")
    raw = _raw(email="different@restaurantex.com.br")
    filled = merge_missing_fields(company, raw)
    assert filled == []
    assert company.email == "original@restaurantex.com.br"


def test_never_overwrites_existing_google_review_data():
    """A later duplicate re-discovery (e.g. Overpass re-finding a company
    Apify already enriched with real review data) must not clobber it —
    same "não sobrescreva cegamente" contract as phone/website/address."""
    company = _company(google_rating=4.9, google_review_count=17566)
    raw = _raw(google_rating=1.0, google_review_count=1)
    filled = merge_missing_fields(company, raw)
    assert filled == []
    assert company.google_rating == 4.9
    assert company.google_review_count == 17566
