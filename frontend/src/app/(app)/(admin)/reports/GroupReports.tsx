"use client";

import { useEffect, useState } from "react";

import { type Column, DataTable, ExportButton, ReportError } from "@/components/reports/ReportParts";
import { useReport } from "@/components/reports/useReport";
import { StatusBadge } from "@/components/ui/StatusBadge";
import {
  type DepartmentRow, getDepartmentReport, getGuardReport, getHostReport, type GuardRow, type HostRow, type RangeChoice,
  type ReportRange,
} from "@/lib/api/reports";
import { formatMinutes } from "@/lib/format";

import { DepartmentSelect, type FilterOptions } from "./filterOptions";

const num = (n: number) => n.toLocaleString();

function Truncated({ shown, total }: { shown: number; total: number }) {
  return (
    <p className="text-sm text-ink-muted">
      Showing the {shown.toLocaleString()} busiest of {total.toLocaleString()}. The CSV export contains all of them.
    </p>
  );
}

const HOST_COLUMNS: Column<HostRow>[] = [
  {
    key: "host", header: "Host",
    cell: (r) => (
      <>
        <span className="caps font-medium">{r.host.name ?? "—"}</span>
        {r.host_unlisted && <span className="ml-1 text-xs text-warn">(not listed)</span>}
      </>
    ),
  },
  { key: "department", header: "Department", className: "caps", cell: (r) => r.department.name ?? "—" },
  { key: "visits", header: "Visits", numeric: true, cell: (r) => num(r.visits) },
  { key: "completed", header: "Completed", numeric: true, cell: (r) => num(r.completed_visits) },
  { key: "inside", header: "Inside now", numeric: true, cell: (r) => num(r.inside_now) },
];

const DEPARTMENT_COLUMNS: Column<DepartmentRow>[] = [
  { key: "department", header: "Department", className: "caps font-medium", cell: (r) => r.department.name ?? "—" },
  { key: "visits", header: "Visits", numeric: true, cell: (r) => num(r.visits) },
  { key: "completed", header: "Completed", numeric: true, cell: (r) => num(r.completed_visits) },
  { key: "unique", header: "Unique visitors", numeric: true, cell: (r) => num(r.unique_visitors) },
  { key: "avg", header: "Average stay", numeric: true, cell: (r) => formatMinutes(r.avg_duration_minutes) },
  { key: "inside", header: "Inside now", numeric: true, cell: (r) => num(r.inside_now) },
];

const GUARD_COLUMNS: Column<GuardRow>[] = [
  {
    key: "guard", header: "Operator",
    cell: (r) => (
      <>
        <span className="font-medium">{r.guard.name ?? "Not recorded"}</span>
        <span className="block text-xs text-ink-muted">
          {r.guard.role === "ADMIN" ? "Administrator" : r.guard.role === "GUARD" ? "Guard" : "—"}
          {r.guard.is_active === false && <> · <StatusBadge tone="neutral">Disabled</StatusBadge></>}
        </span>
      </>
    ),
  },
  { key: "in", header: "Check-ins", numeric: true, cell: (r) => num(r.check_ins) },
  { key: "out", header: "Check-outs", numeric: true, cell: (r) => num(r.check_outs) },
  { key: "inside", header: "Inside now", numeric: true, cell: (r) => num(r.inside_now) },
  { key: "denied", header: "Denied entries", numeric: true, cell: (r) => num(r.denied_entries) },
  { key: "watchlist", header: "Watchlist matches", numeric: true, cell: (r) => num(r.watchlist_matches) },
];

const rowId = (id: string | null, ...rest: (string | null)[]) => [id ?? "none", ...rest.map((x) => x ?? "")].join("|");

export function HostsDepartmentsReport({ range, onPeriod, options }: {
  range: RangeChoice; onPeriod: (r: ReportRange | null) => void; options: FilterOptions;
}) {
  const [department, setDepartment] = useState("");
  const hostFilters = { department_id: department };
  const hosts = useReport(JSON.stringify([range, department]), (signal) => getHostReport(range, hostFilters, { signal }));
  const departments = useReport(JSON.stringify(range), (signal) => getDepartmentReport(range, { signal }));
  useEffect(() => onPeriod(departments.data?.range ?? hosts.data?.range ?? null), [departments.data, hosts.data, onPeriod]);

  return (
    <div className="grid gap-8 xl:grid-cols-2">
      <section aria-labelledby="hosts-heading" className="min-w-0 space-y-3">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div className="min-w-0">
            <h2 id="hosts-heading" className="text-heading text-ink">Hosts</h2>
            <p className="text-sm text-ink-muted">&ldquo;Inside now&rdquo; is the current state.</p>
          </div>
          <ExportButton report="hosts" range={range} filters={hostFilters} />
        </div>
        <div className="max-w-xs">
          <DepartmentSelect departments={options.departments} value={department} onChange={setDepartment} />
        </div>
        {hosts.error
          ? <ReportError error={hosts.error} onRetry={hosts.reload} />
          : <DataTable caption="Visits per host" columns={HOST_COLUMNS} rows={hosts.data?.items ?? []}
                       rowKey={(r) => rowId(r.host.id, r.host.name, r.department.id)} loading={hosts.loading}
                       empty="No hosts were visited in this reporting period." />}
        {hosts.data?.truncated && <Truncated shown={hosts.data.items.length} total={hosts.data.total} />}
      </section>

      <section aria-labelledby="departments-heading" className="min-w-0 space-y-3">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div className="min-w-0">
            <h2 id="departments-heading" className="text-heading text-ink">Departments</h2>
            <p className="text-sm text-ink-muted">Average stay counts completed visits only.</p>
          </div>
          <ExportButton report="departments" range={range} />
        </div>
        {departments.error
          ? <ReportError error={departments.error} onRetry={departments.reload} />
          : <DataTable caption="Visits per department" columns={DEPARTMENT_COLUMNS} rows={departments.data?.items ?? []}
                       rowKey={(r) => rowId(r.department.id, r.department.name)} loading={departments.loading}
                       empty="No departments were visited in this reporting period." />}
        {departments.data?.truncated && <Truncated shown={departments.data.items.length} total={departments.data.total} />}
      </section>
    </div>
  );
}

export function GuardsReport({ range, onPeriod }: { range: RangeChoice; onPeriod: (r: ReportRange | null) => void }) {
  const guards = useReport(JSON.stringify(range), (signal) => getGuardReport(range, { signal }));
  useEffect(() => onPeriod(guards.data?.range ?? null), [guards.data, onPeriod]);
  return (
    <>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-heading text-ink">Guards and operators</h2>
          <p className="text-sm text-ink-muted">
            From the operator recorded with each check-in, check-out and refused entry. Check-outs count by
            check-out time; &ldquo;inside now&rdquo; is the current state.
          </p>
        </div>
        <ExportButton report="guards" range={range} />
      </div>
      {guards.error
        ? <ReportError error={guards.error} onRetry={guards.reload} />
        : <DataTable caption="Activity per operator" columns={GUARD_COLUMNS} rows={guards.data?.items ?? []}
                     rowKey={(r) => rowId(r.guard.id, r.guard.name)} loading={guards.loading}
                     empty="No guard activity in this reporting period." />}
      {guards.data?.truncated && <Truncated shown={guards.data.items.length} total={guards.data.total} />}
    </>
  );
}
