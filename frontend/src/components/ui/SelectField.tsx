import { useId } from "react";

import { type ControlSize, controlClasses, describedBy, FieldMessage } from "./Field";

/** `caps`: the options are human-readable visitor data, shown in capitals (see `caps` in globals.css). */
export function SelectField({ label, hint, error, size, caps = false, className = "", children, ...props }:
  Omit<React.SelectHTMLAttributes<HTMLSelectElement>, "size"> & { label: string; hint?: string; error?: string; size?: ControlSize; caps?: boolean }) {
  const id = useId();
  return (
    <div className={className}>
      <label htmlFor={id} className="mb-1.5 block text-sm font-medium text-ink">{label}</label>
      <select
        id={id}
        {...props}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(id, hint, error)}
        className={`${controlClasses({ error, size })}${caps ? " caps" : ""}`}
      >
        {children}
      </select>
      <FieldMessage id={id} hint={hint} error={error} />
    </div>
  );
}
