"""Encryption of stored secrets (AES-256-GCM, core/secrets.py) and the CG_SECRETS_KEY setting."""
import base64

import pytest
from pydantic import ValidationError

from app.core import secrets
from app.core.config import configuration_problems
from tests.conftest import make_settings

CONTEXT = "gate_camera:0123456789abcdef01234567"


def test_round_trip_with_a_fresh_nonce_each_time():
    key = secrets.parse_key(secrets.generate_key())
    a, b = secrets.encrypt(key, "Cam-Pass-1", CONTEXT), secrets.encrypt(key, "Cam-Pass-1", CONTEXT)
    assert a["nonce"] != b["nonce"] and a["ct"] != b["ct"]                  # same password, different ciphertext
    assert b"Cam-Pass-1" not in a["ct"] and len(a["nonce"]) == 12
    assert secrets.decrypt(key, a, CONTEXT) == secrets.decrypt(key, b, CONTEXT) == "Cam-Pass-1"


def test_a_value_does_not_decrypt_on_another_record():
    key = secrets.parse_key(secrets.generate_key())
    sealed = secrets.encrypt(key, "Cam-Pass-1", CONTEXT)
    with pytest.raises(secrets.SecretUnreadable) as caught:
        secrets.decrypt(key, sealed, "gate_camera:ffffffffffffffffffffffff")
    assert caught.value.other_key is False


def test_another_key_is_recognised_as_such():
    sealed = secrets.encrypt(secrets.parse_key(secrets.generate_key()), "Cam-Pass-1", CONTEXT)
    with pytest.raises(secrets.SecretUnreadable) as caught:
        secrets.decrypt(secrets.parse_key(secrets.generate_key()), sealed, CONTEXT)
    assert caught.value.other_key is True


@pytest.mark.parametrize("damage", [
    lambda s: s | {"ct": bytes([s["ct"][0] ^ 1]) + s["ct"][1:]},          # one bit of the ciphertext
    lambda s: s | {"nonce": b"\0" * 12},
    lambda s: s | {"v": 2},
    lambda s: {k: v for k, v in s.items() if k != "ct"},
    lambda s: None,
])
def test_damaged_values_are_refused(damage):
    key = secrets.parse_key(secrets.generate_key())
    with pytest.raises(secrets.SecretUnreadable):
        secrets.decrypt(key, damage(secrets.encrypt(key, "Cam-Pass-1", CONTEXT)), CONTEXT)


def test_keys_are_32_bytes_of_base64_in_either_alphabet():
    raw = bytes(range(32))
    assert secrets.parse_key(base64.b64encode(raw).decode()) == raw
    assert secrets.parse_key(base64.urlsafe_b64encode(raw).decode().rstrip("=")) == raw
    for bad in ("not base64!", base64.b64encode(b"short").decode(), base64.b64encode(bytes(64)).decode()):
        with pytest.raises(ValueError) as caught:
            secrets.parse_key(bad)
        assert bad not in str(caught.value)


def test_the_setting_is_optional_and_checked_without_revealing_it():
    assert make_settings().secrets_key_bytes is None
    key = secrets.generate_key()
    assert make_settings(secrets_key=key).secrets_key_bytes == secrets.parse_key(key)
    bad = base64.b64encode(b"sixteen-byte-key").decode()
    with pytest.raises(ValidationError) as caught:
        make_settings(secrets_key=bad)
    assert "32 bytes" in configuration_problems(caught.value) and bad not in configuration_problems(caught.value)
