"use client";

import { useEffect, useState } from "react";

import { type Column, DataTable, ExportButton, FilterPanel, LoadMore, ReportError } from "@/components/reports/ReportParts";
import { useKeysetReport } from "@/components/reports/useReport";
import { SelectField } from "@/components/ui/SelectField";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { TextField } from "@/components/ui/TextField";
import {
  getVisitorReport, type RangeChoice, type ReportRange, type VisitorFilters, type VisitorSummaryPage,
  type VisitorSummaryRow,
} from "@/lib/api/reports";
import { formatDateTime, formatMinutes } from "@/lib/format";

import { countActive, DepartmentSelect, type FilterOptions, GateSelect, HostLookup } from "./filterOptions";
import { VisitorCell } from "./visitColumns";

const EMPTY: Required<VisitorFilters> = { q: "", host_id: "", department_id: "", gate_id: "", sort: "last_visit_desc" };

const COLUMNS: Column<VisitorSummaryRow>[] = [
  { key: "visitor", header: "Visitor",
    cell: (r) => <VisitorCell visitor={r.visitor} idType={r.id_type} idNumber={r.id_number} phone={r.phone} /> },
  { key: "visits", header: "Visits", numeric: true, cell: (r) => r.visits.toLocaleString() },
  { key: "completed", header: "Completed", numeric: true, cell: (r) => r.completed_visits.toLocaleString() },
  { key: "first", header: "First visit", className: "whitespace-nowrap", cell: (r) => formatDateTime(r.first_visit_at) },
  { key: "last", header: "Last visit", className: "whitespace-nowrap", cell: (r) => formatDateTime(r.last_visit_at) },
  { key: "avg", header: "Average stay", numeric: true, cell: (r) => formatMinutes(r.avg_duration_minutes) },
  { key: "inside", header: "Inside now",
    cell: (r) => (r.inside_now ? <StatusBadge tone="ok">Inside</StatusBadge> : <span className="text-ink-muted">No</span>) },
];

export function VisitorsReport({ range, onPeriod, options }: {
  range: RangeChoice; onPeriod: (r: ReportRange | null) => void; options: FilterOptions;
}) {
  const [draft, setDraft] = useState(EMPTY);
  const [applied, setApplied] = useState(EMPTY);
  const report = useKeysetReport<VisitorSummaryRow, VisitorSummaryPage>(
    JSON.stringify([range, applied]), (cursor, signal) => getVisitorReport(range, applied, cursor, { signal }));
  useEffect(() => onPeriod(report.first?.range ?? null), [report.first, onPeriod]);
  const set = (patch: Partial<VisitorFilters>) => setDraft({ ...draft, ...patch });

  return (
    <>
      <FilterPanel active={countActive(applied)} onApply={() => setApplied({ ...draft })}
                   onReset={() => { setDraft(EMPTY); setApplied(EMPTY); }}>
        <TextField label="Search" value={draft.q} onChange={(e) => set({ q: e.target.value })}
                   placeholder="Name, ID number or phone" autoComplete="off" spellCheck={false} />
        <HostLookup value={draft.host_id} onChange={(host_id) => set({ host_id })} />
        <DepartmentSelect departments={options.departments} value={draft.department_id}
                          onChange={(department_id) => set({ department_id })} />
        <GateSelect gates={options.gates} value={draft.gate_id} onChange={(gate_id) => set({ gate_id })} />
        <SelectField label="Sort" value={draft.sort} onChange={(e) => set({ sort: e.target.value as VisitorFilters["sort"] })}>
          <option value="last_visit_desc">Most recent visit first</option>
          <option value="visits_desc">Most visits first</option>
        </SelectField>
      </FilterPanel>

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-heading text-ink">Visitors</h2>
          <p className="text-sm text-ink-muted">Each visitor&apos;s visits within the reporting period. &ldquo;Inside now&rdquo; is the current state.</p>
        </div>
        <ExportButton report="visitors" range={range} filters={applied} />
      </div>
      {report.error
        ? <ReportError error={report.error} onRetry={report.reload} />
        : <DataTable caption="Visitors in the reporting period" columns={COLUMNS} rows={report.items}
                     rowKey={(r) => r.visitor.id ?? r.visitor.name ?? ""} loading={report.loading}
                     empty="No visitors found for this reporting period." />}
      <LoadMore shown={report.items.length} total={report.first?.total ?? null} hasMore={report.hasMore}
                loading={report.loading} onMore={report.loadMore} />
    </>
  );
}
