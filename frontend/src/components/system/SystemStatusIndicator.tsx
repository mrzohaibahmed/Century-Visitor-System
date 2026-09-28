"use client";

import { CircleCheck, LoaderCircle, type LucideIcon, TriangleAlert, WifiOff } from "lucide-react";

import type { SystemState } from "@/hooks/useSystemHealth";

export const STATE_LABELS: Record<SystemState, { tone: "ok" | "warn" | "danger" | "neutral"; label: string }> = {
  checking: { tone: "neutral", label: "Checking…" },
  ready: { tone: "ok", label: "System online" },
  degraded: { tone: "warn", label: "Database problem" },
  offline: { tone: "danger", label: "Server unreachable" },
};

// A different shape per state, so the state is clear from the icon alone on narrow screens.
const ICONS: Record<SystemState, LucideIcon> = {
  checking: LoaderCircle, ready: CircleCheck, degraded: TriangleAlert, offline: WifiOff,
};

const TONES = { ok: "text-ok", warn: "text-warn", danger: "text-danger", neutral: "text-ink-muted" } as const;

/** Compact system status for the top bar: icon always, label from md up (always read to screen readers). */
export function SystemStatusIndicator({ state }: { state: SystemState }) {
  const { tone, label } = STATE_LABELS[state];
  const Icon = ICONS[state];
  return (
    <div role="status" aria-live="polite" title={label}
         className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-border bg-surface px-3 text-sm font-medium">
      <Icon aria-hidden="true" className={`size-4 shrink-0 ${TONES[tone]} ${state === "checking" ? "animate-spin" : ""}`} />
      <span className="sr-only text-ink md:not-sr-only">{label}</span>
    </div>
  );
}
