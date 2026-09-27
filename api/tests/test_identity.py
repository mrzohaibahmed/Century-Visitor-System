import pytest

from app.core.identity import (
    IdentityType,
    identifier,
    mask_identity,
    normalize_identity,
    normalize_name,
    normalize_phone,
    search_key,
)


@pytest.mark.parametrize("raw", ["35201-1234567-1", "3520112345671", " 35201 1234567 1 ", "35201-12345671"])
def test_cnic_formats_normalise_to_one_value(raw):
    assert normalize_identity(IdentityType.CNIC, raw) == "35201-1234567-1"


@pytest.mark.parametrize("raw", ["", "35201-123456-1", "352011234567", "35201123456712", "3520A-1234567-1"])
def test_invalid_cnics_are_rejected(raw):
    with pytest.raises(ValueError, match="13 digits"):
        normalize_identity(IdentityType.CNIC, raw)


def test_passport_is_upper_case_and_compact():
    assert normalize_identity(IdentityType.PASSPORT, " ab 12-3456 ") == "AB123456"
    with pytest.raises(ValueError):
        normalize_identity(IdentityType.PASSPORT, "AB$1234")


def test_other_ids():
    assert normalize_identity(IdentityType.OTHER, "  dl /  lhr-123 ") == "DL / LHR-123"
    with pytest.raises(ValueError):
        normalize_identity(IdentityType.OTHER, "x")


def test_identifier_and_masking():
    assert identifier("CNIC", "35201-1234567-1") == "CNIC:35201-1234567-1"
    assert mask_identity("35201-1234567-1") == "***********67-1"
    assert "1234567" not in mask_identity("35201-1234567-1")


@pytest.mark.parametrize("raw,expected", [
    ("0300-1234567", "03001234567"), ("+92 300 1234567", "+923001234567"), ("(042) 3571-2345", "04235712345"),
    ("", None), (None, None),
])
def test_phone_normalisation(raw, expected):
    assert normalize_phone(raw) == expected


@pytest.mark.parametrize("raw", ["123", "0300-123456789012345", "call me"])
def test_implausible_phones_are_rejected(raw):
    with pytest.raises(ValueError):
        normalize_phone(raw)


@pytest.mark.parametrize("raw,expected", [
    ("  Ali   Khan ", "Ali Khan"), ("Mary D'Souza-Khan", "Mary D'Souza-Khan"), ("M. Ali", "M. Ali"),
    ("علی خان", "علی خان"),                          # Urdu names are accepted
])
def test_valid_names(raw, expected):
    assert normalize_name(raw) == expected


@pytest.mark.parametrize("raw", ["A", "Ali2", "-Ali", "Ali <b>", "x" * 101])
def test_invalid_names(raw):
    with pytest.raises(ValueError):
        normalize_name(raw)


def test_search_key_is_case_insensitive():
    assert search_key("  ALI   Khan") == search_key("ali khan") == "ali khan"
