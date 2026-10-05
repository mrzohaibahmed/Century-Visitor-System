"""
Password hashing, password policy and session tokens.

- Passwords: argon2id (argon2-cffi defaults = RFC 9106 low-memory profile:
  t=3, m=64 MiB, p=4). The parameters are stored in each hash, so they can be
  raised later; needs_rehash() then upgrades a hash at the next login.
  Hashing is CPU-heavy (~150 ms): async code must call it via asyncio.to_thread.
- Tokens: 256-bit random values. Only their SHA-256 is ever stored; the raw
  session token exists only in the user's HttpOnly cookie.
"""
import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128

_COMMON_PASSWORDS = {
    "password", "password1", "password12", "password123", "passw0rd", "1234567890", "12345678910",
    "qwertyuiop", "qwerty12345", "iloveyou12", "welcome123", "letmein123", "admin12345", "administrator",
    "centuryadmin123", "century123", "guard12345", "security123", "pakistan123", "abcd123456",
}

_hasher = PasswordHasher()
_dummy_hash: str | None = None


def use_hasher(hasher: PasswordHasher) -> None:
    """Tests swap in cheap parameters; production uses the defaults."""
    global _hasher, _dummy_hash
    _hasher = hasher
    _dummy_hash = None


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, stored_hash: str) -> bool:
    if not password or not stored_hash:
        return False
    try:
        return _hasher.verify(stored_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(stored_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(stored_hash)
    except (InvalidHashError, ValueError):
        return True


def burn_verify_time(password: str) -> None:
    """Same work as a real check, so unknown usernames are not revealed by response time."""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = _hasher.hash(secrets.token_urlsafe(16))
    verify_password(password or "x", _dummy_hash)


def password_policy_error(password: str, username: str = "") -> str | None:
    """A user-facing reason the password is not acceptable, or None."""
    if password is None or len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters long."
    if len(password) > MAX_PASSWORD_LENGTH:
        return f"Password must be at most {MAX_PASSWORD_LENGTH} characters long."
    if len(set(password)) < 4:
        return "Password is too simple. Use a mix of different characters."
    if username and len(username) >= 3 and username.lower() in password.lower():
        return "Password must not contain the username."
    if password.lower() in _COMMON_PASSWORDS:
        return "This password is too common. Choose a different one."
    return None


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def tokens_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
