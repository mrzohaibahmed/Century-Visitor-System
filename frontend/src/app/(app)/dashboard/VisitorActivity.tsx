"use client";

import { ArrowRight, RefreshCw, UsersRound } from "lucide-react";
import Link from "next/link";

import { Alert } from "@/components/ui/Alert";
import { Avatar } from "@/components/ui/Avatar";
import { Button, ButtonLink } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Skeleton";
import { StatusBadge } from "@/components/ui/StatusBadge";
import type { Visit } from "@/lib/api/visits";
import { formatDuration, formatTime } from "@/lib/format";

import { isLongStay, type Loadable, type Today } from "./useDashboardData";

const SHOWN = 10;

function VisitStatus({ visit, now }: { visit: Visit; now: number }) {
  if (visit.status === "CHECKED_OUT") return <StatusBadge tone="neutral">Checked out</StatusBadge>;
  return isLongStay(visit, now) ? <StatusBadge tone="warn">Long stay</StatusBadge> : <StatusBadge tone="ok">On site</StatusBadge>;
}

function VisitorName({ visit }: { visit: Visit }) {
  const name = visit.visitor.name ?? "Unknown visitor";
  return visit.visitor.id
    ? <Link href={`/visitors/${visit.visitor.id}`} className="caps font-semibold text-ink hover:text-brand-700 hover:underline">{name}</Link>
    : <span className="caps font-semibold text-ink">{name}</span>;
}

function Host({ visit }: { visit: Visit }) {
  return (
    <>
      <span className="caps text-ink">{visit.host.name ?? "—"}</span>
      {visit.host_unlisted && <span className="ml-1.5 text-xs font-medium text-warn">(not listed)</span>}
      {visit.department.name && <span className="caps block text-xs text-ink-muted">{visit.department.name}</span>}
    </>
  );
}

/** Today's check-ins, newest first: a table from md up, visitor cards on phones. */
export function VisitorActivity({ today, now, loadedAt, refreshing, onRefresh }: {
  today: Loadable<Today>;
  now: number;
  loadedAt: number | null;
  refreshing: boolean;
  onRefresh: () => void;
}) {
  const items = today.data?.items ?? [];
  const shown = items.slice(0, SHOWN);
  return (
    <section aria-labelledby="activity-heading" className="rounded-2xl border border-border bg-surface shadow-card">
      <header className="flex items-start justify-between gap-3 border-b border-border px-5 py-4 sm:items-center sm:px-6">
        <div className="min-w-0">
          <h2 id="activity-heading" className="text-heading text-ink">Today&apos;s visitor activity</h2>
          <p className="mt-0.5 text-sm text-ink-muted">
            Check-ins since midnight, newest first{loadedAt ? ` · updated ${formatTime(new Date(loadedAt).toISOString())}` : ""}
          </p>
        </div>
        <Button variant="ghost" onClick={onRefresh} disabled={refreshing} aria-label="Refresh dashboard" className="shrink-0">
          <RefreshCw aria-hidden="true" className={refreshing ? "animate-spin" : ""} />
          <span className="hidden sm:inline">Refresh</span>
        </Button>
      </header>

      {today.error && (
        <div className="px-5 pt-4 sm:px-6">
          <Alert tone={today.data ? "warn" : "danger"} title={today.data ? "Could not refresh today's visits" : "Unable to load today's visits"}>
            {today.error}
          </Alert>
        </div>
      )}

      {today.data === null && !today.error && (
        <div role="status" className="space-y-4 px-5 py-5 sm:px-6">
          <span className="sr-only">Loading today&apos;s visits…</span>
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="flex items-center gap-3">
              <Skeleton className="size-9 rounded-full" />
              <Skeleton className="h-4 flex-1" />
              <Skeleton className="h-4 w-20" />
            </div>
          ))}
        </div>
      )}

      {today.data !== null && items.length === 0 && (
        <div className="flex flex-col items-center gap-3 px-6 py-12 text-center">
          <span aria-hidden="true" className="flex size-12 items-center justify-center rounded-full bg-surface-subtle text-ink-muted">
            <UsersRound className="size-6" />
          </span>
          <p className="font-semibold text-ink">No visitors today yet</p>
          <p className="max-w-xs text-sm text-ink-muted">Check-ins will appear here as they happen.</p>
        </div>
      )}

      {shown.length > 0 && (
        <>
          {/* md and up: a table. `relative` keeps its sr-only caption inside the scroll box. */}
          <div className="relative hidden overflow-x-auto md:block">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">Today&apos;s visits, newest first</caption>
              <thead className="border-b border-border text-xs font-medium uppercase tracking-wide text-ink-muted">
                <tr>
                  <th scope="col" className="px-6 py-3 font-medium">Visitor</th>
                  <th scope="col" className="px-4 py-3 font-medium">Host</th>
                  <th scope="col" className="px-4 py-3 font-medium">In</th>
                  <th scope="col" className="px-4 py-3 font-medium">Out</th>
                  <th scope="col" className="px-6 py-3 font-medium">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {shown.map((v) => (
                  <tr key={v.id} className="transition-colors hover:bg-surface-subtle">
                    <td className="px-6 py-3">
                      <div className="flex items-center gap-3">
                        <Avatar name={v.visitor.name ?? ""} size="sm" />
                        <div className="min-w-0">
                          <VisitorName visit={v} />
                          <span className="block font-mono text-xs text-ink-muted">{v.visit_number}</span>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3"><Host visit={v} /></td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      <span className="text-ink tabular-nums">{formatTime(v.check_in_at)}</span>
                      <span className="caps block text-xs text-ink-muted">{v.gate.name}</span>
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      <span className="text-ink tabular-nums">{formatTime(v.check_out_at)}</span>
                      {v.check_out_at && (
                        <span className="block text-xs text-ink-muted">{formatDuration(v.check_in_at, v.check_out_at)}</span>
                      )}
                    </td>
                    <td className="px-6 py-3"><VisitStatus visit={v} now={now} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Phones: one card per visitor. */}
          <ul aria-label="Today's visits, newest first" className="divide-y divide-border md:hidden">
            {shown.map((v) => (
              <li key={v.id} className="flex gap-3 px-5 py-4">
                <Avatar name={v.visitor.name ?? ""} size="sm" />
                <div className="min-w-0 flex-1 space-y-1">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <VisitorName visit={v} />
                      <span className="block font-mono text-xs text-ink-muted">{v.visit_number}</span>
                    </div>
                    <VisitStatus visit={v} now={now} />
                  </div>
                  <p className="text-sm"><Host visit={v} /></p>
                  <p className="text-sm text-ink-muted tabular-nums">
                    In {formatTime(v.check_in_at)}
                    {v.check_out_at ? ` · Out ${formatTime(v.check_out_at)}` : ""} · <span className="caps">{v.gate.name}</span>
                  </p>
                </div>
              </li>
            ))}
          </ul>
        </>
      )}

      {today.data !== null && items.length > 0 && (
        <footer className="border-t border-border px-5 py-3 sm:px-6">
          <ButtonLink href="/visits" variant="ghost" className="-ml-3">
            {items.length > SHOWN
              ? `View all ${today.data.capped ? `${items.length}+` : items.length} of today's visits`
              : "Open visit history"}
            <ArrowRight aria-hidden="true" />
          </ButtonLink>
        </footer>
      )}
    </section>
  );
}
