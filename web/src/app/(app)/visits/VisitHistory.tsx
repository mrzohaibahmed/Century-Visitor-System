"use client";

import { useEffect, useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { SelectField } from "@/components/ui/SelectField";
import { TextField } from "@/components/ui/TextField";
import { VisitTable } from "@/components/visits/VisitTable";
import { usePagedList } from "@/hooks/usePagedList";
import { type Department, type Gate, listDepartments, listGates } from "@/lib/api/directory";
import { listVisits, type VisitFilters, visitQuery } from "@/lib/api/visits";
import { isoDay } from "@/lib/format";

const EMPTY: VisitFilters = { q: "", status: "", from: isoDay(), to: isoDay(), gate_id: "", department_id: "" };

export function VisitHistory() {
  const [draft, setDraft] = useState<VisitFilters>(EMPTY);
  const [applied, setApplied] = useState<VisitFilters>(EMPTY);
  const [gates, setGates] = useState<Gate[]>([]);
  const [departments, setDepartments] = useState<Department[]>([]);
  const list = usePagedList(visitQuery(applied), (cursor) => listVisits(applied, cursor));
  const set = (changes: Partial<VisitFilters>) => setDraft({ ...draft, ...changes });

  useEffect(() => {
    const controller = new AbortController();
    // Include inactive entries so old visits stay filterable (the API only honours this for admins).
    listGates(true, controller.signal).then(setGates).catch(() => {});
    listDepartments(true, controller.signal).then(setDepartments).catch(() => {});
    return () => controller.abort();
  }, []);

  function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (visitQuery(draft) === visitQuery(applied)) list.reload();
    else setApplied({ ...draft });
  }

  const rangeError = draft.from && draft.to && draft.from > draft.to ? "The start date is after the end date." : undefined;
  return (
    <div className="space-y-4">
      <form onSubmit={onSubmit} className="grid gap-3 rounded-xl border border-border bg-surface p-4 shadow-sm sm:grid-cols-3 lg:grid-cols-6">
        <TextField label="Visitor" className="sm:col-span-3 lg:col-span-2" value={draft.q ?? ""}
                   onChange={(e) => set({ q: e.target.value })} placeholder="Name, ID or phone" />
        <TextField label="From" type="date" value={draft.from ?? ""} onChange={(e) => set({ from: e.target.value })} />
        <TextField label="To" type="date" value={draft.to ?? ""} onChange={(e) => set({ to: e.target.value })} error={rangeError} />
        <SelectField label="Status" value={draft.status ?? ""} onChange={(e) => set({ status: e.target.value as VisitFilters["status"] })}>
          <option value="">All</option>
          <option value="CHECKED_IN">Inside</option>
          <option value="CHECKED_OUT">Checked out</option>
        </SelectField>
        <SelectField label="Gate" value={draft.gate_id ?? ""} onChange={(e) => set({ gate_id: e.target.value })}>
          <option value="">All gates</option>
          {gates.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
        </SelectField>
        <SelectField label="Department" className="lg:col-span-2" value={draft.department_id ?? ""}
                     onChange={(e) => set({ department_id: e.target.value })}>
          <option value="">All departments</option>
          {departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
        </SelectField>
        <div className="flex items-end gap-2 sm:col-span-2 lg:col-span-4 lg:justify-end">
          <Button type="button" variant="secondary" onClick={() => { setDraft(EMPTY); setApplied(EMPTY); }}>Reset</Button>
          <Button type="button" variant="ghost" onClick={() => set({ from: "", to: "" })}>Any date</Button>
          <Button type="submit" disabled={Boolean(rangeError)}>Apply filters</Button>
        </div>
      </form>

      {list.error && <Alert tone="danger">{list.error}</Alert>}
      <VisitTable visits={list.items} loading={list.loading} empty="No visits match these filters." />
      {list.hasMore && (
        <div className="flex justify-center">
          <Button variant="secondary" onClick={list.loadMore} loading={list.loading}>Load more</Button>
        </div>
      )}
    </div>
  );
}
