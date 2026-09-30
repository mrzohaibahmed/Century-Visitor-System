"use client";

import { RefreshCw } from "lucide-react";
import { useState } from "react";

import { DataTable, ExportButton, FilterPanel, LoadMore, ReportError } from "@/components/reports/ReportParts";
import { useKeysetReport } from "@/components/reports/useReport";
import { Button } from "@/components/ui/Button";
import { SelectField } from "@/components/ui/SelectField";
import { TextField } from "@/components/ui/TextField";
import { getInsideReport, type InsideFilters, type InsidePage, type VisitReportRow } from "@/lib/api/reports";
import { formatTime } from "@/lib/format";

import { countActive, DepartmentSelect, type FilterOptions, GateSelect, HostLookup } from "./filterOptions";
import { INSIDE_COLUMNS } from "./visitColumns";

const EMPTY: Required<InsideFilters> = { q: "", host_id: "", department_id: "", gate_id: "", sort: "check_in_asc" };

/** Who is on site right now: the current state, never limited by the reporting period. Refreshed on
 * request (no polling). Check-out stays in the existing check-out screen. */
export function InsideReport({ options }: { options: FilterOptions }) {
  const [draft, setDraft] = useState(EMPTY);
  const [applied, setApplied] = useState(EMPTY);
  const report = useKeysetReport<VisitReportRow, InsidePage>(
    JSON.stringify(applied), (cursor, signal) => getInsideReport(applied, cursor, { signal }));
  const set = (patch: Partial<InsideFilters>) => setDraft({ ...draft, ...patch });

  return (
    <>
      <FilterPanel active={countActive(applied)} onApply={() => setApplied({ ...draft })}
                   onReset={() => { setDraft(EMPTY); setApplied(EMPTY); }}>
        <TextField label="Search" value={draft.q} onChange={(e) => set({ q: e.target.value })}
                   placeholder="Name, ID number, phone or visit number" autoComplete="off" spellCheck={false} />
        <HostLookup value={draft.host_id} onChange={(host_id) => set({ host_id })} />
        <DepartmentSelect departments={options.departments} value={draft.department_id}
                          onChange={(department_id) => set({ department_id })} />
        <GateSelect gates={options.gates} value={draft.gate_id} onChange={(gate_id) => set({ gate_id })} />
        <SelectField label="Sort" value={draft.sort} onChange={(e) => set({ sort: e.target.value as InsideFilters["sort"] })}>
          <option value="check_in_asc">Longest inside first</option>
          <option value="check_in_desc">Most recent arrivals first</option>
        </SelectField>
      </FilterPanel>

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-heading text-ink">Currently inside</h2>
          <p className="text-sm text-ink-muted" aria-live="polite">
            Everyone on site right now, whenever they arrived.
            {report.first && ` Updated at ${formatTime(report.first.generated_at)}.`}
          </p>
        </div>
        <div className="flex flex-wrap items-start gap-2">
          <Button variant="ghost" onClick={report.reload} loading={report.loading}>
            {!report.loading && <RefreshCw aria-hidden="true" />} Refresh
          </Button>
          <ExportButton report="inside" range={null} filters={applied} />
        </div>
      </div>
      {report.error
        ? <ReportError error={report.error} onRetry={report.reload} />
        : <DataTable caption="Visitors currently inside" columns={INSIDE_COLUMNS} rows={report.items}
                     rowKey={(r) => r.id} loading={report.loading} empty="Nobody is inside right now." />}
      <LoadMore shown={report.items.length} total={report.first?.total ?? null} hasMore={report.hasMore}
                loading={report.loading} onMore={report.loadMore} />
    </>
  );
}
