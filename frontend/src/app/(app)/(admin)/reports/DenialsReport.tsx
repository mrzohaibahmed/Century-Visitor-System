"use client";

import { ShieldAlert, ShieldX } from "lucide-react";
import { useEffect, useState } from "react";

import { type Column, DataTable, ExportButton, FilterPanel, LoadMore, LookupField, ReportError } from "@/components/reports/ReportParts";
import { useKeysetReport } from "@/components/reports/useReport";
import { SelectField } from "@/components/ui/SelectField";
import { StatTile } from "@/components/ui/StatTile";
import {
  type DenialFilters, type DenialPage, type DenialRow, type DenialSource, getDenialReport, type RangeChoice,
  type ReportRange,
} from "@/lib/api/reports";
import { reasonLabel } from "@/lib/api/visits";
import { formatDateTime } from "@/lib/format";

import { countActive, type FilterOptions, GateSelect } from "./filterOptions";

const SOURCES: Record<DenialSource, string> = {
  check_in: "At check-in",
  lookup: "At the ID lookup",
  audit_backfill: "From earlier records",
};
const REASONS: Record<string, string> = { WATCHLIST: "Watchlist" };

const EMPTY: Required<DenialFilters> = { source: "", guard_id: "", gate_id: "" };

/** A name filled from the current records (older rebuilt refusals) is marked, not passed off as recorded. */
function Named({ row, kind, name }: { row: DenialRow; kind: DenialRow["current_names"][number]; name: string | null }) {
  const current = row.current_names.includes(kind);
  return (
    <span className="caps">
      {name ?? "—"}
      {current && <span className="ml-1 text-xs text-ink-muted normal-case" title="Name from the current records">(current name)</span>}
    </span>
  );
}

const COLUMNS: Column<DenialRow>[] = [
  { key: "at", header: "Time", className: "whitespace-nowrap", cell: (r) => formatDateTime(r.at) },
  {
    key: "visitor", header: "Visitor",
    cell: (r) => (
      <>
        <Named row={r} kind="visitor" name={r.visitor.name} />
        {r.identifier && <span data-testid="masked-id" className="block font-mono text-xs text-ink-muted">{r.identifier}</span>}
      </>
    ),
  },
  {
    key: "reason", header: "Reason",
    cell: (r) => (
      <>
        <span className="font-medium">{REASONS[r.reason] ?? r.reason}</span>
        {r.reason_code && <span className="caps block text-xs text-ink-muted">Purpose: {reasonLabel(r.reason_code)}</span>}
      </>
    ),
  },
  { key: "watchlist", header: "Watchlist entry", className: "max-w-xs", cell: (r) => r.watchlist.reason ?? "—" },
  { key: "source", header: "Where", className: "whitespace-nowrap", cell: (r) => SOURCES[r.source] ?? r.source },
  { key: "gate", header: "Gate", cell: (r) => <Named row={r} kind="gate" name={r.gate.name} /> },
  { key: "operator", header: "Operator", cell: (r) => <Named row={r} kind="operator" name={r.operator.name} /> },
];

export function DenialsReport({ range, onPeriod, options }: {
  range: RangeChoice; onPeriod: (r: ReportRange | null) => void; options: FilterOptions;
}) {
  const [draft, setDraft] = useState(EMPTY);
  const [applied, setApplied] = useState(EMPTY);
  const report = useKeysetReport<DenialRow, DenialPage>(
    JSON.stringify([range, applied]), (cursor, signal) => getDenialReport(range, applied, cursor, { signal }));
  useEffect(() => onPeriod(report.first?.range ?? null), [report.first, onPeriod]);
  const first = report.first;
  const unknown = report.error ? "—" : null;

  return (
    <>
      <div className="grid gap-4 sm:grid-cols-2" role="region" aria-label="Security totals">
        <StatTile label="Denied entries" icon={<ShieldX />} tone="warn" testId="denied-entries"
                  value={first ? first.denied_entries.toLocaleString() : unknown}
                  hint="Every entry refused at the gate in this period, whatever the reason." />
        <StatTile label="Watchlist matches" icon={<ShieldAlert />} tone="warn" testId="watchlist-matches"
                  value={first ? first.watchlist_matches.toLocaleString() : unknown}
                  hint="Refusals because the person is on the watchlist. Counted separately: other refusal reasons would be denials only." />
      </div>

      <FilterPanel active={countActive(applied)} onApply={() => setApplied({ ...draft })}
                   onReset={() => { setDraft(EMPTY); setApplied(EMPTY); }}>
        <SelectField label="Where" value={draft.source}
                     onChange={(e) => setDraft({ ...draft, source: e.target.value as DenialSource | "" })}>
          <option value="">Anywhere</option>
          {Object.entries(SOURCES).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </SelectField>
        <LookupField label="Operator" options={options.guards} value={draft.guard_id}
                     onChange={(guard_id) => setDraft({ ...draft, guard_id })} placeholder="Any operator" />
        <GateSelect gates={options.gates} value={draft.gate_id} onChange={(gate_id) => setDraft({ ...draft, gate_id })} />
      </FilterPanel>

      <div className="flex flex-wrap items-start justify-between gap-3">
        <h2 className="text-heading text-ink">Refused entries</h2>
        <ExportButton report="denials" range={range} filters={applied} />
      </div>
      {report.error
        ? <ReportError error={report.error} onRetry={report.reload} />
        : <DataTable caption="Entries refused in the reporting period" columns={COLUMNS} rows={report.items}
                     rowKey={(r) => r.id} loading={report.loading} empty="No security events in this reporting period." />}
      <LoadMore shown={report.items.length} total={first?.total ?? null} hasMore={report.hasMore}
                loading={report.loading} onMore={report.loadMore} />
    </>
  );
}
