"""
Encryption of secrets the application has to keep in the database (gate camera passwords).

AES-256-GCM (cryptography's AESGCM). The 32-byte key exists only in the server environment
(CG_SECRETS_KEY, generated with `python -m app.cli generate-secrets-key`), never in the database or
the repository: a copy of the database alone does not reveal a password.

Each value is stored as {"v": 1, "kid": ..., "nonce": <12 random bytes>, "ct": <ciphertext + tag>}.
`context` (e.g. "gate_camera:<gate id>") is bound to the ciphertext as associated data, so a value
copied onto another record does not decrypt. `kid` is a short fingerprint of the key, only used to
say "encrypted with a different key" instead of "damaged"; it reveals nothing about the key.

A password that must be sent to a device (Digest login) cannot be hashed: it has to be recoverable.
"""
import base64
import binascii
import hashlib
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_BYTES = 32                      # AES-256
NONCE_BYTES = 12
FORMAT_VERSION = 1


class SecretUnreadable(ValueError):
    """A stored secret cannot be decrypted: other key, damaged value or wrong record."""

    def __init__(self, other_key: bool):
        super().__init__("encrypted with a different key" if other_key else "damaged or not for this record")
        self.other_key = other_key


def generate_key() -> str:
    """A new random key, as text for CG_SECRETS_KEY."""
    return base64.urlsafe_b64encode(os.urandom(KEY_BYTES)).decode("ascii")


def parse_key(text: str) -> bytes:
    """CG_SECRETS_KEY (base64, standard or URL-safe) → 32 bytes. The message never contains the value."""
    raw = text.strip()
    try:
        key = base64.b64decode(raw.replace("-", "+").replace("_", "/") + "=" * (-len(raw) % 4), validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("CG_SECRETS_KEY must be base64 text (use: python -m app.cli generate-secrets-key).") from None
    if len(key) != KEY_BYTES:
        raise ValueError("CG_SECRETS_KEY must hold exactly 32 bytes (use: python -m app.cli generate-secrets-key).")
    return key


def key_id(key: bytes) -> str:
    return hashlib.sha256(b"cgvms-secrets-key-id:" + key).hexdigest()[:8]


def encrypt(key: bytes, plaintext: str, context: str) -> dict:
    nonce = os.urandom(NONCE_BYTES)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), context.encode("utf-8"))
    return {"v": FORMAT_VERSION, "kid": key_id(key), "nonce": nonce, "ct": ciphertext}


def decrypt(key: bytes, sealed: dict, context: str) -> str:
    if not isinstance(sealed, dict) or sealed.get("v") != FORMAT_VERSION:
        raise SecretUnreadable(other_key=False)
    if sealed.get("kid") != key_id(key):
        raise SecretUnreadable(other_key=True)
    try:
        return AESGCM(key).decrypt(bytes(sealed["nonce"]), bytes(sealed["ct"]), context.encode("utf-8")).decode("utf-8")
    except (InvalidTag, KeyError, TypeError, ValueError):
        raise SecretUnreadable(other_key=False) from None
