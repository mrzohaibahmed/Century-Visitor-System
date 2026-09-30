"use client";

import { useEffect, useState } from "react";

import { DataTable, ExportButton, FilterPanel, LoadMore, LookupField, ReportError } from "@/components/reports/ReportParts";
import { useKeysetReport } from "@/components/reports/useReport";
import { SelectField } from "@/components/ui/SelectField";
import { TextField } from "@/components/ui/TextField";
import {
  getVisitReport, type RangeChoice, type ReportRange, type VisitFilters, type VisitReportPage, type VisitReportRow,
} from "@/lib/api/reports";
import { VISIT_REASONS } from "@/lib/api/visits";

import { countActive, DepartmentSelect, type FilterOptions, GateSelect, HostLookup } from "./filterOptions";
import { VISIT_COLUMNS } from "./visitColumns";

const EMPTY: Required<VisitFilters> = {
  q: "", status: "", host_id: "", department_id: "", gate_id: "", guard_id: "", reason_code: "", sort: "check_in_desc",
};

export function VisitsReport({ range, onPeriod, options }: {
  range: RangeChoice; onPeriod: (r: ReportRange | null) => void; options: FilterOptions;
}) {
  const [draft, setDraft] = useState(EMPTY);
  const [applied, setApplied] = useState(EMPTY);
  const report = useKeysetReport<VisitReportRow, VisitReportPage>(
    JSON.stringify([range, applied]), (cursor, signal) => getVisitReport(range, applied, cursor, { signal }));
  useEffect(() => onPeriod(report.first?.range ?? null), [report.first, onPeriod]);
  const set = (patch: Partial<VisitFilters>) => setDraft({ ...draft, ...patch });

  return (
    <>
      <FilterPanel active={countActive(applied)} onApply={() => setApplied({ ...draft })}
                   onReset={() => { setDraft(EMPTY); setApplied(EMPTY); }}>
        <TextField label="Search" value={draft.q} onChange={(e) => set({ q: e.target.value })}
                   placeholder="Name, ID number, phone or visit number" autoComplete="off" spellCheck={false} />
        <SelectField label="Status" value={draft.status} onChange={(e) => set({ status: e.target.value as VisitFilters["status"] })}>
          <option value="">Any status</option>
          <option value="CHECKED_IN">Inside</option>
          <option value="CHECKED_OUT">Checked out</option>
        </SelectField>
        <HostLookup value={draft.host_id} onChange={(host_id) => set({ host_id })} />
        <DepartmentSelect departments={options.departments} value={draft.department_id}
                          onChange={(department_id) => set({ department_id })} />
        <GateSelect gates={options.gates} value={draft.gate_id} onChange={(gate_id) => set({ gate_id })} />
        <LookupField label="Guard (checked in or out)" options={options.guards} value={draft.guard_id}
                     onChange={(guard_id) => set({ guard_id })} placeholder="Any operator" />
        <SelectField label="Purpose" value={draft.reason_code}
                     onChange={(e) => set({ reason_code: e.target.value as VisitFilters["reason_code"] })}>
          <option value="">Any purpose</option>
          {VISIT_REASONS.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
        </SelectField>
        <SelectField label="Sort" value={draft.sort} onChange={(e) => set({ sort: e.target.value as VisitFilters["sort"] })}>
          <option value="check_in_desc">Newest first</option>
          <option value="check_in_asc">Oldest first</option>
          <option value="check_out_desc">Latest check-out first</option>
          <option value="duration_desc">Longest visits first</option>
        </SelectField>
      </FilterPanel>

      <div className="flex flex-wrap items-start justify-between gap-3">
        <h2 className="text-heading text-ink">Visits</h2>
        <ExportButton report="visits" range={range} filters={applied} />
      </div>
      {report.error
        ? <ReportError error={report.error} onRetry={report.reload} />
        : <DataTable caption="Visits in the reporting period" columns={VISIT_COLUMNS} rows={report.items}
                     rowKey={(r) => r.id} loading={report.loading} empty="No visits found for this reporting period." />}
      <LoadMore shown={report.items.length} total={report.first?.total ?? null} hasMore={report.hasMore}
                loading={report.loading} onMore={report.loadMore} />
    </>
  );
}
