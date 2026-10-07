/** Mirrors backend `app.core.identity.normalize_phone`. */

const PHONE_CHARS = /^[\d\s+\-()]*$/;

/**
 * Canonical phone for the API: digits only, with a leading `+` kept when present.
 * Empty / whitespace → `null`. Throws with a user-facing message if implausible.
 */
export function normalizePhone(raw: string | null | undefined): string | null {
  if (raw == null || !raw.trim()) return null;
  const value = raw.trim();
  const plus = value.startsWith("+");
  const digits = value.replace(/\D/g, "");
  if (digits.length !== 11 || !PHONE_CHARS.test(value)) {
    throw new Error("Enter a valid phone number (11 digits).");
  }
  return (plus ? "+" : "") + digits;
}

/** `null` when empty or valid; otherwise the message to show under the field. */
export function phoneError(raw: string): string | null {
  try {
    normalizePhone(raw);
    return null;
  } catch (e) {
    return e instanceof Error ? e.message : "Enter a valid phone number.";
  }
}
