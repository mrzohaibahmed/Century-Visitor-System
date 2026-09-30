import Link from "next/link";

import type { Column } from "@/components/reports/ReportParts";
import { VisitStatusBadge } from "@/components/visits/VisitStatusBadge";
import type { Ref, VisitReportRow } from "@/lib/api/reports";
import { reasonLabel } from "@/lib/api/visits";
import { formatDateTime, formatMinutes } from "@/lib/format";

/** The visitor with the ID number and phone as the server sent them: already masked. */
export function VisitorCell({ visitor, idType, idNumber, phone }: {
  visitor: Ref; idType: string | null; idNumber: string | null; phone: string | null;
}) {
  return (
    <>
      {visitor.id
        ? <Link href={`/visitors/${visitor.id}`} className="caps font-medium text-brand-700 hover:underline">{visitor.name}</Link>
        : <span className="caps font-medium">{visitor.name ?? "—"}</span>}
      {(idNumber || phone) && (
        <span className="block font-mono text-xs text-ink-muted">
          {idNumber && <span data-testid="masked-id">{idType} {idNumber}</span>}
          {idNumber && phone && " · "}
          {phone && <span data-testid="masked-phone">{phone}</span>}
        </span>
      )}
    </>
  );
}

function HostCell({ row }: { row: VisitReportRow }) {
  return (
    <>
      <span className="caps">{row.host.name ?? "—"}</span>
      {row.host_unlisted && <span className="ml-1 text-xs text-warn">(not listed)</span>}
      <span className="caps block text-xs text-ink-muted">{row.department.name ?? ""}</span>
    </>
  );
}

const visitor: Column<VisitReportRow> = {
  key: "visitor", header: "Visitor",
  cell: (r) => <VisitorCell visitor={r.visitor} idType={r.id_type} idNumber={r.id_number} phone={r.phone} />,
};
const number: Column<VisitReportRow> = {
  key: "number", header: "Visit", className: "font-mono whitespace-nowrap", cell: (r) => r.visit_number,
};
const host: Column<VisitReportRow> = { key: "host", header: "Host / department", cell: (r) => <HostCell row={r} /> };
const gate: Column<VisitReportRow> = { key: "gate", header: "Gate", className: "caps", cell: (r) => r.gate.name ?? "—" };
const checkIn: Column<VisitReportRow> = {
  key: "in", header: "Check-in", className: "whitespace-nowrap", cell: (r) => formatDateTime(r.check_in_at),
};

export const VISIT_COLUMNS: Column<VisitReportRow>[] = [
  number, visitor, host,
  { key: "purpose", header: "Purpose", className: "caps", cell: (r) => reasonLabel(r.reason_code) },
  gate, checkIn,
  { key: "out", header: "Check-out", className: "whitespace-nowrap", cell: (r) => (r.check_out_at ? formatDateTime(r.check_out_at) : "—") },
  { key: "duration", header: "Duration", numeric: true, className: "whitespace-nowrap", cell: (r) => formatMinutes(r.duration_minutes) },
  { key: "status", header: "Status", cell: (r) => <VisitStatusBadge status={r.status} /> },
  {
    key: "by", header: "Handled by",
    cell: (r) => (
      <span className="text-xs">
        <span className="block">In: {r.checked_in_by.name ?? "—"}</span>
        {r.checked_out_by && <span className="block text-ink-muted">Out: {r.checked_out_by.name ?? "—"}</span>}
      </span>
    ),
  },
];

export const INSIDE_COLUMNS: Column<VisitReportRow>[] = [
  number, visitor, host, gate, checkIn,
  { key: "elapsed", header: "Inside for", numeric: true, className: "whitespace-nowrap", cell: (r) => formatMinutes(r.duration_minutes) },
  { key: "by", header: "Checked in by", cell: (r) => r.checked_in_by.name ?? "—" },
];
