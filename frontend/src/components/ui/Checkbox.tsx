import { useId } from "react";

import { describedBy, FieldMessage } from "./Field";

/** A checkbox whose whole row (44 px high) is the touch target. */
export function Checkbox({ label, hint, error, className = "", ...props }:
  Omit<React.InputHTMLAttributes<HTMLInputElement>, "type"> & { label: React.ReactNode; hint?: string; error?: string }) {
  const id = useId();
  return (
    <div className={className}>
      <label htmlFor={id} className="flex min-h-11 cursor-pointer items-center gap-3 text-base text-ink has-disabled:cursor-not-allowed has-disabled:text-ink-muted">
        <input
          id={id}
          type="checkbox"
          {...props}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy(id, hint, error)}
          className="size-5 shrink-0 cursor-pointer rounded accent-brand-600 disabled:cursor-not-allowed"
        />
        <span>{label}</span>
      </label>
      <FieldMessage id={id} hint={hint} error={error} />
    </div>
  );
}
