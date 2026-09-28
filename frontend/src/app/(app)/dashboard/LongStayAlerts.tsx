"use client";

import { CircleCheck, Clock, TriangleAlert } from "lucide-react";
import Link from "next/link";

import { Alert } from "@/components/ui/Alert";
import { ButtonLink } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Skeleton";
import type { Visit } from "@/lib/api/visits";
import { formatDuration } from "@/lib/format";

import { LONG_STAY_HOURS } from "./useDashboardData";

const SHOWN = 5;

/** Visitors inside longer than LONG_STAY_HOURS (the dashboard's existing alert), longest first. */
export function LongStayAlerts({ longStays, error, now }: {
  longStays: Visit[] | null;
  error: string | null;
  now: number;
}) {
  const sorted = [...(longStays ?? [])].sort((a, b) => a.check_in_at.localeCompare(b.check_in_at));
  return (
    <section aria-labelledby="alerts-heading" className="flex flex-col rounded-2xl border border-border bg-surface shadow-card">
      <header className="flex items-center gap-3 border-b border-border px-5 py-4 sm:px-6">
        <span aria-hidden="true" className="flex size-9 items-center justify-center rounded-xl bg-warn-bg text-warn">
          <TriangleAlert className="size-5" />
        </span>
        <div>
          <h2 id="alerts-heading" className="text-heading text-ink">Alerts</h2>
          <p className="text-sm text-ink-muted">Visitors inside longer than {LONG_STAY_HOURS} hours</p>
        </div>
      </header>
      <div className="flex-1 px-5 py-4 sm:px-6">
        {error && !longStays && <Alert tone="danger" title="Unable to load visitors inside">{error}</Alert>}
        {!longStays && !error && (
          <div role="status" className="space-y-3">
            <span className="sr-only">Loading alerts…</span>
            <Skeleton className="h-5 w-3/4" />
            <Skeleton className="h-5 w-1/2" />
          </div>
        )}
        {longStays && sorted.length === 0 && (
          <p className="flex items-center gap-3 py-2 text-sm text-ink-muted">
            <CircleCheck aria-hidden="true" className="size-5 shrink-0 text-ok" />
            No alerts. Nobody has been inside longer than {LONG_STAY_HOURS} hours.
          </p>
        )}
        {sorted.length > 0 && (
          <ul className="divide-y divide-border">
            {sorted.slice(0, SHOWN).map((v) => (
              <li key={v.id} className="flex items-center gap-3 py-3 first:pt-0 last:pb-0">
                <Clock aria-hidden="true" className="size-5 shrink-0 text-warn" />
                <div className="min-w-0 flex-1">
                  {v.visitor.id
                    ? <Link href={`/visitors/${v.visitor.id}`} className="font-semibold text-ink hover:text-brand-700 hover:underline">{v.visitor.name}</Link>
                    : <span className="font-semibold text-ink">{v.visitor.name}</span>}
                  <span className="block truncate text-sm text-ink-muted">
                    <span className="font-mono">{v.visit_number}</span> · visiting {v.host.name ?? "—"}
                  </span>
                </div>
                <span className="shrink-0 text-sm font-semibold whitespace-nowrap text-warn tabular-nums">
                  {formatDuration(v.check_in_at, null, new Date(now))}
                </span>
              </li>
            ))}
          </ul>
        )}
        {sorted.length > SHOWN && (
          <p className="mt-3 text-sm text-ink-muted">and {sorted.length - SHOWN} more.</p>
        )}
      </div>
      {sorted.length > 0 && (
        <footer className="border-t border-border px-5 py-3 sm:px-6">
          <ButtonLink href="/check-out" variant="ghost" className="-ml-3">Go to check-out</ButtonLink>
        </footer>
      )}
    </section>
  );
}
