import { useId } from "react";

import { type ControlSize, controlClasses, describedBy, FieldMessage } from "./Field";

/** `caps`: human-readable visitor data, shown in capitals as typed (the value itself is unchanged; see `caps` in globals.css). */
export function TextField({ label, hint, error, size, caps = false, className = "", ...props }:
  Omit<React.InputHTMLAttributes<HTMLInputElement>, "size"> & { label: string; hint?: string; error?: string; size?: ControlSize; caps?: boolean }) {
  const id = useId();
  return (
    <div className={className}>
      <label htmlFor={id} className="mb-1.5 block text-sm font-medium text-ink">{label}</label>
      <input
        id={id}
        {...props}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(id, hint, error)}
        className={`${controlClasses({ error, size })} py-2${caps ? " caps" : ""}`}
      />
      <FieldMessage id={id} hint={hint} error={error} />
    </div>
  );
}
