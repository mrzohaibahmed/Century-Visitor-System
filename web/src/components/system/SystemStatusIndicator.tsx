"use client";

import { StatusBadge } from "@/components/ui/StatusBadge";
import type { SystemState } from "@/hooks/useSystemHealth";

export const STATE_LABELS: Record<SystemState, { tone: "ok" | "warn" | "danger" | "neutral"; label: string }> = {
  checking: { tone: "neutral", label: "Checking…" },
  ready: { tone: "ok", label: "System online" },
  degraded: { tone: "warn", label: "Database problem" },
  offline: { tone: "danger", label: "Server unreachable" },
};

export function SystemStatusIndicator({ state }: { state: SystemState }) {
  const { tone, label } = STATE_LABELS[state];
  return (
    <div role="status" aria-live="polite">
      <StatusBadge tone={tone}>{label}</StatusBadge>
    </div>
  );
}
