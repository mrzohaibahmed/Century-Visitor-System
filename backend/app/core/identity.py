"""
Normalisation of identity documents, phone numbers and names.

Everything that stores or compares an identity number goes through
normalize_identity(), so "3520112345671", "35201-1234567-1" and
" 35201 1234567 1 " are the same person, and watchlist screening cannot be
bypassed by formatting (the desktop app's exact-string bug).
"""
import re
from enum import StrEnum


class IdentityType(StrEnum):
    CNIC = "CNIC"          # Pakistani national identity card
    PASSPORT = "PASSPORT"
    OTHER = "OTHER"        # e.g. driving licence, company ID


_SEPARATORS = re.compile(r"[\s\-]")
_PASSPORT = re.compile(r"^[A-Z0-9]{5,20}$")
_OTHER = re.compile(r"^[A-Z0-9][A-Z0-9 /\-]{2,39}$")
# Letters in any script (Urdu names work), plus spaces, dots, apostrophes and hyphens; no digits.
_NAME = re.compile(r"^[^\W\d_](?:[^\W\d_]|[ .'\-])*$")


def normalize_identity(id_type: IdentityType | str, raw: str) -> str:
    """Canonical form of an identity number. Raises ValueError with a user-facing message."""
    id_type = IdentityType(id_type)
    value = (raw or "").strip()
    if id_type is IdentityType.CNIC:
        digits = _SEPARATORS.sub("", value)
        if len(digits) != 13 or not digits.isdigit():
            raise ValueError("A CNIC must have exactly 13 digits.")
        return f"{digits[:5]}-{digits[5:12]}-{digits[12]}"
    if id_type is IdentityType.PASSPORT:
        compact = _SEPARATORS.sub("", value).upper()
        if not _PASSPORT.match(compact):
            raise ValueError("A passport number must be 5–20 letters or digits.")
        return compact
    collapsed = re.sub(r"\s+", " ", value).upper()
    if not _OTHER.match(collapsed):
        raise ValueError("The ID number must be 3–40 characters (letters, digits, space, / or -).")
    return collapsed


def identifier(id_type: IdentityType | str, number: str) -> str:
    """Key used by the watchlist: "CNIC:35201-1234567-1"."""
    return f"{IdentityType(id_type)}:{number}"


def mask_identity(number: str) -> str:
    """For audit records and logs: keeps only the last 4 characters."""
    return "*" * max(len(number) - 4, 0) + number[-4:]


def mask_sensitive(value: str | None) -> str | None:
    """For reports and exports (ID numbers and phone numbers): mask_identity(), but never showing more
    than half of a short value, so a 3-character "other ID" is not shown in full. None stays None."""
    if not value:
        return value
    if len(value) >= 8:
        return mask_identity(value)
    visible = len(value) // 2
    return "*" * (len(value) - visible) + (value[-visible:] if visible else "")


def normalize_phone(raw: str | None) -> str | None:
    """Pakistani local (0XXXXXXXXXX) or international (+92XXXXXXXXXX) phone. None if empty."""
    if raw is None or not raw.strip():
        return None
    value = raw.strip()
    if re.search(r"[^\d\s\-+()]", value) or "+" in value[1:]:
        raise ValueError("Enter a valid Pakistani phone number (11 digits, or +92 followed by 10 digits).")
    digits = re.sub(r"\D", "", value)
    if value.startswith("+"):
        if len(digits) == 12 and digits.startswith("92") and digits[2] != "0":
            return "+" + digits
    elif len(digits) == 11 and digits.startswith("0"):
        return digits
    raise ValueError("Enter a valid Pakistani phone number (11 digits, or +92 followed by 10 digits).")


def normalize_name(raw: str) -> str:
    """Trimmed, single-spaced display name. Raises ValueError if it is not a plausible name."""
    name = re.sub(r"\s+", " ", (raw or "").strip())
    if not 2 <= len(name) <= 100 or not _NAME.match(name):
        raise ValueError("The name must be 2–100 characters: letters, spaces, dots, apostrophes or hyphens.")
    return name


def search_key(name: str) -> str:
    """Case-insensitive search key for prefix matching."""
    return re.sub(r"\s+", " ", name).strip().casefold()
