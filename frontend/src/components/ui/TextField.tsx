"use client";

import { Eye, EyeOff } from "lucide-react";
import { useId, useState } from "react";

import { type ControlSize, controlClasses, describedBy, FieldMessage } from "./Field";

/** `caps`: human-readable visitor data, shown in capitals as typed (the value itself is unchanged; see `caps` in globals.css).
 *  Password fields get a show/hide toggle inside the input's right edge. */
export function TextField({ label, hint, error, size, caps = false, className = "", type, ...props }:
  Omit<React.InputHTMLAttributes<HTMLInputElement>, "size"> & { label: string; hint?: string; error?: string; size?: ControlSize; caps?: boolean }) {
  const id = useId();
  const [revealed, setRevealed] = useState(false);
  const isPassword = type === "password";
  const input = (
    <input
      id={id}
      {...props}
      type={isPassword && revealed ? "text" : type}
      aria-invalid={error ? true : undefined}
      aria-describedby={describedBy(id, hint, error)}
      className={`${controlClasses({ error, size })} py-2${isPassword ? " pr-12" : ""}${caps ? " caps" : ""}`}
    />
  );
  return (
    <div className={className}>
      <label htmlFor={id} className="mb-1.5 block text-sm font-medium text-ink">{label}</label>
      {isPassword ? (
        <div className="relative">
          {input}
          {/* Named by its text, not aria-label, so label lookups for the field itself stay unambiguous. */}
          <button
            type="button"
            onClick={() => setRevealed((v) => !v)}
            aria-pressed={revealed}
            disabled={props.disabled}
            className="absolute inset-y-0 right-1 my-auto flex size-10 items-center justify-center rounded-lg text-ink-muted
              transition-colors hover:text-ink focus-visible:outline-2 focus-visible:outline-brand-600 disabled:pointer-events-none"
          >
            {revealed ? <EyeOff aria-hidden="true" className="size-5" /> : <Eye aria-hidden="true" className="size-5" />}
            <span className="sr-only">{revealed ? "Hide" : "Show"} {label.toLowerCase()}</span>
          </button>
        </div>
      ) : input}
      <FieldMessage id={id} hint={hint} error={error} />
    </div>
  );
}
