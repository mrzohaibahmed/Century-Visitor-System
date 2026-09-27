import Link from "next/link";

import type { Visit } from "@/lib/api/visits";
import { reasonLabel } from "@/lib/api/visits";
import { formatDateTime, formatDuration } from "@/lib/format";

import { VisitStatusBadge } from "./VisitStatusBadge";

/** Visit list used by the history page and a visitor's own history. */
export function VisitTable({ visits, loading, empty = "No visits found.", showVisitor = true }: {
  visits: Visit[];
  loading?: boolean;
  empty?: string;
  showVisitor?: boolean;
}) {
  const columns = showVisitor ? 7 : 6;
  return (
    <div className="overflow-x-auto rounded-xl border border-border bg-surface shadow-sm">
      <table className="w-full text-left text-sm">
        <thead className="bg-canvas text-xs uppercase tracking-wide text-ink-muted">
          <tr>
            <th scope="col" className="px-4 py-3">Visit</th>
            {showVisitor && <th scope="col" className="px-4 py-3">Visitor</th>}
            <th scope="col" className="px-4 py-3">Host / department</th>
            <th scope="col" className="px-4 py-3">Reason</th>
            <th scope="col" className="px-4 py-3">In</th>
            <th scope="col" className="px-4 py-3">Out</th>
            <th scope="col" className="px-4 py-3">Status</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {visits.length === 0 && (
            <tr><td colSpan={columns} className="px-4 py-8 text-center text-ink-muted">{loading ? "Loading…" : empty}</td></tr>
          )}
          {visits.map((v) => (
            <tr key={v.id} data-testid="visit-row">
              <td className="px-4 py-3 font-mono">{v.visit_number}</td>
              {showVisitor && (
                <td className="px-4 py-3 font-medium">
                  {v.visitor.id
                    ? <Link href={`/visitors/${v.visitor.id}`} className="text-brand-700 hover:underline">{v.visitor.name}</Link>
                    : v.visitor.name}
                </td>
              )}
              <td className="px-4 py-3">
                {v.host.name}
                {v.host_unlisted && <span className="ml-1 text-xs text-warn">(not listed)</span>}
                <span className="block text-xs text-ink-muted">{v.department.name ?? ""}</span>
              </td>
              <td className="px-4 py-3">{reasonLabel(v.reason_code)}</td>
              <td className="px-4 py-3">
                {formatDateTime(v.check_in_at)}
                <span className="block text-xs text-ink-muted">{v.gate.name}</span>
              </td>
              <td className="px-4 py-3">
                {v.check_out_at ? formatDateTime(v.check_out_at) : "—"}
                {v.check_out_at && (
                  <span className="block text-xs text-ink-muted">{formatDuration(v.check_in_at, v.check_out_at)}</span>
                )}
              </td>
              <td className="px-4 py-3"><VisitStatusBadge status={v.status} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
