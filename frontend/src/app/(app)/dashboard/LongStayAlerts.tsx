"use client";

import { CircleCheck, Clock, TriangleAlert } from "lucide-react";
import Link from "next/link";

import { Alert } from "@/components/ui/Alert";
import { ButtonLink } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Skeleton";
import { formatDuration } from "@/lib/format";

import type { ExpiredBadgeVisit } from "./useDashboardData";

const SHOWN = 5;

/** Visitors still inside after badge expiry, earliest expiry first. */
export function LongStayAlerts({ expiredBadges, error, now }: {
  expiredBadges: ExpiredBadgeVisit[] | null;
  error: string | null;
  now: number;
}) {
  const sorted = [...(expiredBadges ?? [])].sort((a, b) => a.badge_expires_at.localeCompare(b.badge_expires_at));
  return (
    <section aria-labelledby="alerts-heading" className="flex flex-col rounded-2xl border border-border bg-surface shadow-card">
      <header className="flex items-center gap-3 border-b border-border px-5 py-4 sm:px-6">
        <span aria-hidden="true" className="flex size-9 items-center justify-center rounded-xl bg-warn-bg text-warn">
          <TriangleAlert className="size-5" />
        </span>
        <div>
          <h2 id="alerts-heading" className="text-heading text-ink">Alerts</h2>
          <p className="text-sm text-ink-muted">Visitors still inside after badge expiry</p>
        </div>
      </header>
      <div className="flex-1 px-5 py-4 sm:px-6">
        {error && !expiredBadges && <Alert tone="danger" title="Unable to load visitors inside">{error}</Alert>}
        {!expiredBadges && !error && (
          <div role="status" className="space-y-3">
            <span className="sr-only">Loading alerts…</span>
            <Skeleton className="h-5 w-3/4" />
            <Skeleton className="h-5 w-1/2" />
          </div>
        )}
        {expiredBadges && sorted.length === 0 && (
          <p className="flex items-center gap-3 py-2 text-sm text-ink-muted">
            <CircleCheck aria-hidden="true" className="size-5 shrink-0 text-ok" />
            No alerts. Nobody is still inside with an expired badge.
          </p>
        )}
        {sorted.length > 0 && (
          <ul className="divide-y divide-border">
            {sorted.slice(0, SHOWN).map((v) => (
              <li key={v.id} className="flex items-center gap-3 py-3 first:pt-0 last:pb-0">
                <Clock aria-hidden="true" className="size-5 shrink-0 text-warn" />
                <div className="min-w-0 flex-1">
                  {v.visitor.id
                    ? <Link href={`/visitors/${v.visitor.id}`} className="caps font-semibold text-ink hover:text-brand-700 hover:underline">{v.visitor.name}</Link>
                    : <span className="caps font-semibold text-ink">{v.visitor.name}</span>}
                  <span className="block truncate text-sm text-ink-muted">
                    <span className="font-mono">{v.visit_number}</span> · visiting <span className="caps">{v.host.name ?? "—"}</span>
                  </span>
                </div>
                <span className="shrink-0 text-sm font-semibold whitespace-nowrap text-warn tabular-nums">
                  Expired {formatDuration(v.badge_expires_at, null, new Date(now))} ago
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
