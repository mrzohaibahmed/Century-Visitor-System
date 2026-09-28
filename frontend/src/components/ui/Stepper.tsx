import { Check } from "lucide-react";

/**
 * Progress through a multi-step flow. Completed steps show a check. The current step's name is
 * always shown in full; the other names appear from lg up (below that they stay available to
 * screen readers), so the row never wraps or truncates.
 */
export function Stepper({ steps, current, label }: { steps: string[]; current: number; label: string }) {
  return (
    <ol aria-label={label} className="flex items-center gap-2 sm:gap-3">
      {steps.map((title, i) => {
        const state = i < current ? "done" : i === current ? "current" : "upcoming";
        const last = i === steps.length - 1;
        return (
          <li key={title} aria-current={state === "current" ? "step" : undefined}
              className={`flex items-center gap-2 sm:gap-3 ${last ? "flex-none" : "flex-1"} ${state === "current" ? "" : "min-w-0"}`}>
            <span className={`flex size-8 shrink-0 items-center justify-center rounded-full text-sm font-semibold transition-colors ${
              state === "upcoming" ? "border border-border-strong bg-surface text-ink-muted"
                : `bg-brand-600 text-white ${state === "current" ? "ring-4 ring-brand-100" : ""}`}`}>
              {state === "done" ? <Check aria-hidden="true" className="size-4" strokeWidth={3} /> : i + 1}
            </span>
            <span className={`text-sm whitespace-nowrap ${state === "current"
              ? "shrink-0 font-semibold text-ink" : "sr-only font-medium text-ink-muted lg:not-sr-only"}`}>
              {title}{state === "done" && <span className="sr-only"> (done)</span>}
            </span>
            {!last && (
              <span aria-hidden="true" className={`h-0.5 min-w-4 flex-1 rounded-full transition-colors ${
                state === "done" ? "bg-brand-600" : "bg-border"}`} />
            )}
          </li>
        );
      })}
    </ol>
  );
}
