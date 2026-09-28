import { useId } from "react";

import { type ControlSize, controlClasses, describedBy, FieldMessage } from "./Field";

export function SelectField({ label, hint, error, size, className = "", children, ...props }:
  Omit<React.SelectHTMLAttributes<HTMLSelectElement>, "size"> & { label: string; hint?: string; error?: string; size?: ControlSize }) {
  const id = useId();
  return (
    <div className={className}>
      <label htmlFor={id} className="mb-1.5 block text-sm font-medium text-ink">{label}</label>
      <select
        id={id}
        {...props}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(id, hint, error)}
        className={controlClasses({ error, size })}
      >
        {children}
      </select>
      <FieldMessage id={id} hint={hint} error={error} />
    </div>
  );
}
