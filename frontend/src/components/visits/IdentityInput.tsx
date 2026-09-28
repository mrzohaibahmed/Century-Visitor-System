import type { ControlSize } from "@/components/ui/Field";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { SelectField } from "@/components/ui/SelectField";
import { TextField } from "@/components/ui/TextField";
import { IDENTITY_LABELS, type IdentityType } from "@/lib/api/visitors";

const PLACEHOLDERS: Record<IdentityType, string> = {
  CNIC: "3520112345671",
  PASSPORT: "AB1234567",
  OTHER: "Driving licence or other document number",
};

const TYPES = (Object.keys(IDENTITY_LABELS) as IdentityType[]).map((t) => ({ value: t, label: IDENTITY_LABELS[t] }));

export const CNIC_DIGITS = 13;

/** A CNIC field accepts digits only, at most 13 (typed or pasted "35201-1234567-1" keeps its digits). */
export function cnicDigits(value: string): string {
  return value.replace(/\D/g, "").slice(0, CNIC_DIGITS);
}

/**
 * ID type + number. For a CNIC only digits can be entered, 13 at most; the server also refuses anything but
 * exactly 13. Passports and other IDs are normalised by the API (dashes/spaces), so any common typing is fine.
 * size="lg" (gate check-in) shows the types as one-tap options stacked above a large number field.
 */
export function IdentityInput({ type, number, onType, onNumber, error, autoFocus, size = "md" }: {
  type: IdentityType;
  number: string;
  onType: (t: IdentityType) => void;
  onNumber: (n: string) => void;
  error?: string;
  autoFocus?: boolean;
  size?: ControlSize;
}) {
  const cnic = type === "CNIC";
  // Switching to CNIC drops whatever cannot be part of one (e.g. the letters of a passport number).
  const chooseType = (t: IdentityType) => {
    onType(t);
    if (t === "CNIC" && number !== cnicDigits(number)) onNumber(cnicDigits(number));
  };
  // No maxLength: the browser would cut a pasted "35201-1234567-1" to 13 characters before the dashes go.
  const numberField = (
    <TextField label="ID number" value={number} error={error} size={size}
               onChange={(e) => onNumber(cnic ? cnicDigits(e.target.value) : e.target.value)}
               placeholder={PLACEHOLDERS[type]} autoComplete="off" spellCheck={false}
               autoFocus={autoFocus} inputMode={cnic ? "numeric" : undefined}
               hint={cnic ? `Exactly 13 digits, numbers only (${cnicDigits(number).length} of 13).` : undefined} />
  );
  if (size === "lg") {
    return (
      <div className="space-y-5">
        <SegmentedControl label="ID type" value={type} options={TYPES} onChange={chooseType} size="lg" />
        {numberField}
      </div>
    );
  }
  return (
    <div className="grid gap-3 sm:grid-cols-[10rem_1fr]">
      <SelectField label="ID type" value={type} onChange={(e) => chooseType(e.target.value as IdentityType)}>
        {TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
      </SelectField>
      {numberField}
    </div>
  );
}
