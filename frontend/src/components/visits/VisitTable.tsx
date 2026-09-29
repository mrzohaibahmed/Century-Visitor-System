import { CalendarX } from "lucide-react";
import Link from "next/link";

import { Skeleton } from "@/components/ui/Skeleton";
import type { Visit } from "@/lib/api/visits";
import { reasonLabel } from "@/lib/api/visits";
import { formatDateTime, formatDuration } from "@/lib/format";

import { VisitStatusBadge } from "./VisitStatusBadge";

function VisitorName({ visit }: { visit: Visit }) {
  return visit.visitor.id
    ? <Link href={`/visitors/${visit.visitor.id}`} className="caps font-medium text-brand-700 hover:underline">{visit.visitor.name}</Link>
    : <span className="caps font-medium">{visit.visitor.name}</span>;
}

function Host({ visit }: { visit: Visit }) {
  return (
    <>
      <span className="caps">{visit.host.name}</span>
      {visit.host_unlisted && <span className="ml-1 text-xs text-warn">(not listed)</span>}
    </>
  );
}

/**
 * Visit list used by the history page and a visitor's own history: a table from lg (its six or
 * seven columns do not fit a tablet without scrolling sideways), one card per visit below. Only the
 * table rows carry data-testid="visit-row", so each visit is found exactly once.
 */
export function VisitTable({ visits, loading, empty = "No visits found.", showVisitor = true }: {
  visits: Visit[];
  loading?: boolean;
  empty?: string;
  showVisitor?: boolean;
}) {
  return (
    <div className="rounded-2xl border border-border bg-surface shadow-card">
      {visits.length === 0 && loading && (
        <div role="status" className="space-y-4 p-5 sm:p-6">
          <span className="sr-only">Loading visits…</span>
          {[0, 1, 2].map((i) => (
            <div key={i} className="flex items-center gap-4">
              <Skeleton className="h-4 w-28" />
              <Skeleton className="h-4 flex-1" />
              <Skeleton className="h-6 w-20 rounded-full" />
            </div>
          ))}
        </div>
      )}

      {visits.length === 0 && !loading && (
        <div className="flex flex-col items-center gap-2 px-6 py-10 text-center">
          <span aria-hidden="true" className="flex size-11 items-center justify-center rounded-full bg-surface-subtle text-ink-muted">
            <CalendarX className="size-5" />
          </span>
          <p className="text-sm text-ink-muted">{empty}</p>
        </div>
      )}

      {visits.length > 0 && (
        <>
          <div className="relative hidden overflow-x-auto lg:block">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-border text-xs uppercase tracking-wide text-ink-muted">
                <tr>
                  <th scope="col" className="px-5 py-3 font-medium">Visit</th>
                  {showVisitor && <th scope="col" className="px-4 py-3 font-medium">Visitor</th>}
                  <th scope="col" className="px-4 py-3 font-medium">Host / department</th>
                  <th scope="col" className="px-4 py-3 font-medium">Reason</th>
                  <th scope="col" className="px-4 py-3 font-medium">In</th>
                  <th scope="col" className="px-4 py-3 font-medium">Out</th>
                  <th scope="col" className="px-5 py-3 font-medium">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {visits.map((v) => (
                  <tr key={v.id} data-testid="visit-row" className="align-top transition-colors hover:bg-surface-subtle">
                    <td className="px-5 py-3 font-mono whitespace-nowrap text-ink">{v.visit_number}</td>
                    {showVisitor && <td className="px-4 py-3"><VisitorName visit={v} /></td>}
                    <td className="px-4 py-3 text-ink">
                      <Host visit={v} />
                      <span className="caps block text-xs text-ink-muted">{v.department.name ?? ""}</span>
                    </td>
                    <td className="caps px-4 py-3 text-ink">{reasonLabel(v.reason_code)}</td>
                    <td className="px-4 py-3 whitespace-nowrap text-ink">
                      {formatDateTime(v.check_in_at)}
                      <span className="caps block text-xs text-ink-muted">{v.gate.name}</span>
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-ink">
                      {v.check_out_at ? formatDateTime(v.check_out_at) : "—"}
                      {v.check_out_at && (
                        <span className="block text-xs text-ink-muted">{formatDuration(v.check_in_at, v.check_out_at)}</span>
                      )}
                    </td>
                    <td className="px-5 py-3"><VisitStatusBadge status={v.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <ul aria-label="Visits" className="divide-y divide-border lg:hidden">
            {visits.map((v) => (
              <li key={v.id} className="space-y-2 px-5 py-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    {showVisitor && <p className="truncate"><VisitorName visit={v} /></p>}
                    <p className="font-mono text-sm text-ink">{v.visit_number}</p>
                  </div>
                  <VisitStatusBadge status={v.status} />
                </div>
                <p className="text-sm text-ink">
                  <Host visit={v} />
                  {v.department.name && <span className="caps text-ink-muted"> · {v.department.name}</span>}
                  <span className="caps text-ink-muted"> · {reasonLabel(v.reason_code)}</span>
                </p>
                <dl className="grid grid-cols-2 gap-3 text-sm">
                  <div className="min-w-0">
                    <dt className="text-xs text-ink-muted">In · <span className="caps">{v.gate.name}</span></dt>
                    <dd className="text-ink">{formatDateTime(v.check_in_at)}</dd>
                  </div>
                  <div className="min-w-0">
                    <dt className="text-xs text-ink-muted">Out</dt>
                    <dd className="text-ink">
                      {v.check_out_at ? formatDateTime(v.check_out_at) : "—"}
                      {v.check_out_at && <span className="block text-xs text-ink-muted">{formatDuration(v.check_in_at, v.check_out_at)}</span>}
                    </dd>
                  </div>
                </dl>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
