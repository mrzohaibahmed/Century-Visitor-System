/** Mirrors backend `app.core.identity.normalize_phone`. */

const PHONE_CHARS = /^[\d\s+\-()]*$/;
export const PHONE_ERROR = "Enter a valid Pakistani phone number (11 digits, or +92 followed by 10 digits).";

/**
 * Canonical Pakistani phone for the API: local 0XXXXXXXXXX or international +92XXXXXXXXXX.
 * Empty / whitespace → `null`. Throws with a user-facing message if implausible.
 */
export function normalizePhone(raw: string | null | undefined): string | null {
  if (raw == null || !raw.trim()) return null;
  const value = raw.trim();
  const plus = value.startsWith("+");
  const digits = value.replace(/\D/g, "");
  if (!PHONE_CHARS.test(value) || value.slice(1).includes("+")) throw new Error(PHONE_ERROR);
  if (plus) {
    if (digits.length === 12 && digits.startsWith("92") && digits[2] !== "0") return `+${digits}`;
  } else if (digits.length === 11 && digits.startsWith("0")) {
    return digits;
  }
  throw new Error(PHONE_ERROR);
}

/** `null` when empty or valid; otherwise the message to show under the field. */
export function phoneError(raw: string): string | null {
  try {
    normalizePhone(raw);
    return null;
  } catch (e) {
    return e instanceof Error ? e.message : PHONE_ERROR;
  }
}
