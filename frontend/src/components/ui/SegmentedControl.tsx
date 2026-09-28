import { useId } from "react";

import type { ControlSize } from "./Field";

/**
 * A short set of mutually exclusive options shown side by side (native radio buttons, so arrow
 * keys and screen readers work as usual). Better than a select when there are 2–4 options and
 * the user is on a touch screen: one tap, and the current choice is always visible.
 */
export function SegmentedControl<T extends string>({ label, value, options, onChange, size = "md" }: {
  label: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
  size?: ControlSize;
}) {
  const name = useId();
  return (
    <fieldset>
      <legend className="mb-1.5 block text-sm font-medium text-ink">{label}</legend>
      <div className="flex gap-1 rounded-xl bg-canvas p-1">
        {options.map((o) => (
          <label key={o.value}
                 className={`flex flex-1 cursor-pointer items-center justify-center rounded-lg px-3 text-center font-medium
                   text-ink-muted transition-colors hover:text-ink has-checked:bg-surface has-checked:text-ink has-checked:shadow-card
                   has-focus-visible:outline-2 has-focus-visible:outline-brand-600
                   ${size === "lg" ? "min-h-12 text-base" : "min-h-9 text-sm"}`}>
            <input type="radio" name={name} value={o.value} checked={value === o.value}
                   onChange={() => onChange(o.value)} className="sr-only" />
            {o.label}
          </label>
        ))}
      </div>
    </fieldset>
  );
}
