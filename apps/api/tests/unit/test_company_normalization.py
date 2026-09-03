import pytest

from app.modules.companies.service import (
    extract_domain,
    name_similarity,
    normalize_name,
    normalize_phone,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Restaurante São João", "restaurante sao joao"),
        ("  Café   Central  ", "cafe central"),
        ("Pizzaria N.1!", "pizzaria n 1"),
        ("ACME LTDA.", "acme ltda"),
    ],
)
def test_normalize_name(raw, expected):
    assert normalize_name(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("(15) 3231-4455", "1532314455"),
        ("+55 15 99999-8888", "+5515999998888"),
        (None, None),
        ("", None),
        ("n/a", None),
    ],
)
def test_normalize_phone(raw, expected):
    assert normalize_phone(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("https://www.example.com/menu", "example.com"),
        ("http://example.com", "example.com"),
        ("example.com", "example.com"),
        (None, None),
        ("", None),
    ],
)
def test_extract_domain(raw, expected):
    assert extract_domain(raw) == expected


def test_name_similarity_identical_is_one():
    assert name_similarity("restaurante sao joao", "restaurante sao joao") == 1.0


def test_name_similarity_unrelated_is_low():
    assert name_similarity("restaurante sao joao", "clinica saude total") < 0.5
