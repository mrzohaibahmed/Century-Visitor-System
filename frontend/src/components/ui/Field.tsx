import { CircleAlert } from "lucide-react";

export type ControlSize = "md" | "lg";

/** Shared look of text inputs, selects and text areas. lg is for touch-first gate flows. */
export function controlClasses({ error, size = "md" }: { error?: string; size?: ControlSize }): string {
  return `block w-full rounded-xl border bg-surface px-3.5 text-ink transition-colors placeholder:text-ink-muted/70
    hover:border-ink-muted/50 focus-visible:border-brand-600 focus-visible:outline-2 focus-visible:outline-offset-0
    disabled:cursor-not-allowed disabled:bg-canvas disabled:text-ink-muted
    ${size === "lg" ? "min-h-14 text-lg" : "min-h-11 text-base"}
    ${error ? "border-danger" : "border-border-strong"}`;
}

/** The hint under a field, replaced by the error when there is one (icon + text, never colour alone). */
export function FieldMessage({ id, hint, error }: { id: string; hint?: string; error?: string }) {
  if (error) {
    return (
      <p id={`${id}-error`} className="mt-1.5 flex items-start gap-1.5 text-sm text-danger">
        <CircleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
        <span>{error}</span>
      </p>
    );
  }
  return hint ? <p id={`${id}-hint`} className="mt-1.5 text-sm text-ink-muted">{hint}</p> : null;
}

export function describedBy(id: string, hint?: string, error?: string): string | undefined {
  return [hint && !error && `${id}-hint`, error && `${id}-error`].filter(Boolean).join(" ") || undefined;
}
