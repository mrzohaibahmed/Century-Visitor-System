import { SelectField } from "@/components/ui/SelectField";
import { TextField } from "@/components/ui/TextField";
import { IDENTITY_LABELS, type IdentityType } from "@/lib/api/visitors";

const PLACEHOLDERS: Record<IdentityType, string> = {
  CNIC: "35201-1234567-1",
  PASSPORT: "AB1234567",
  OTHER: "Driving licence or other document number",
};

/** ID type + number. The API normalises formats (dashes/spaces), so any common way of typing is fine. */
export function IdentityInput({ type, number, onType, onNumber, error, autoFocus }: {
  type: IdentityType;
  number: string;
  onType: (t: IdentityType) => void;
  onNumber: (n: string) => void;
  error?: string;
  autoFocus?: boolean;
}) {
  return (
    <div className="grid gap-3 sm:grid-cols-[10rem_1fr]">
      <SelectField label="ID type" value={type} onChange={(e) => onType(e.target.value as IdentityType)}>
        {(Object.keys(IDENTITY_LABELS) as IdentityType[]).map((t) => (
          <option key={t} value={t}>{IDENTITY_LABELS[t]}</option>
        ))}
      </SelectField>
      <TextField label="ID number" value={number} onChange={(e) => onNumber(e.target.value)} error={error}
                 placeholder={PLACEHOLDERS[type]} autoComplete="off" spellCheck={false} autoFocus={autoFocus}
                 hint={type === "CNIC" ? "13 digits, with or without dashes." : undefined} />
    </div>
  );
}
