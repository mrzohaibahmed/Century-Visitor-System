"use client";

import { Activity, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { StatusBadge } from "@/components/ui/StatusBadge";
import type { SystemHealth } from "@/hooks/useSystemHealth";
import type { CheckState } from "@/lib/api/health";

import { STATE_LABELS } from "./SystemStatusIndicator";

const CHECK_NAMES: Record<string, string> = {
  database: "Database connection",
  schema_version: "Database schema",
  transactions: "Transactions (replica set)",
  photo_storage: "Photo storage",
};

const CHECK_TEXT: Record<CheckState, { tone: "ok" | "warn" | "danger" | "neutral"; text: string }> = {
  ok: { tone: "ok", text: "OK" },
  unavailable: { tone: "danger", text: "Unavailable" },
  missing: { tone: "warn", text: "Not set up — run the migration" },
  outdated: { tone: "warn", text: "Outdated — run the migration" },
  unknown: { tone: "neutral", text: "Not checked" },
};

export function SystemStatusCard({ health }: { health: SystemHealth }) {
  const { state, checks, version, checkedAt, refresh } = health;
  const summary = STATE_LABELS[state];

  return (
    <Card
      title="System status"
      icon={<Activity />}
      description={checkedAt ? `Last checked ${checkedAt.toLocaleTimeString()}` : "Checking the server…"}
      actions={
        <Button variant="secondary" onClick={refresh} className="shrink-0">
          <RefreshCw aria-hidden="true" />
          Check again
        </Button>
      }
    >
      <div className="mb-4">
        <StatusBadge tone={summary.tone}>{summary.label}</StatusBadge>
      </div>

      {state === "offline" && (
        <p className="text-sm text-danger">
          The application server cannot be reached. Check the network connection or contact the administrator.
        </p>
      )}

      {checks && (
        <dl className="divide-y divide-border">
          {Object.entries(checks).map(([key, value]) => (
            <div key={key} className="flex items-center justify-between py-2.5">
              <dt className="text-sm text-ink">{CHECK_NAMES[key] ?? key}</dt>
              <dd><StatusBadge tone={CHECK_TEXT[value].tone}>{CHECK_TEXT[value].text}</StatusBadge></dd>
            </div>
          ))}
        </dl>
      )}

      {version && <p className="mt-4 text-xs text-ink-muted">API version {version}</p>}
    </Card>
  );
}
