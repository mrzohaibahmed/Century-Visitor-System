"use client";

import { useEffect, useState } from "react";

import { LookupField, type Option, uniqueOptions } from "@/components/reports/ReportParts";
import { useReport } from "@/components/reports/useReport";
import { SelectField } from "@/components/ui/SelectField";
import { type Department, type Gate, type Host, listDepartments, listGates, listHosts } from "@/lib/api/directory";
import { listUsers } from "@/lib/api/users";

export type FilterOptions = { gates: Gate[]; departments: Department[]; guards: Option[] };

/** Gates, departments and operators for the filters (inactive ones too: reports cover the past).
 * Loaded once, the first time a report with filters is opened. */
export function useFilterOptions(enabled: boolean): FilterOptions {
  const gates = useReport(enabled ? "gates" : null, (signal) => listGates(true, signal));
  const departments = useReport(enabled ? "departments" : null, (signal) => listDepartments(true, signal));
  const users = useReport(enabled ? "users" : null, (signal) => listUsers(signal));
  return {
    gates: gates.data ?? [],
    departments: departments.data ?? [],
    guards: uniqueOptions((users.data?.items ?? []).map((u) => ({ id: u.id, label: u.display_name || u.username }))),
  };
}

const hostLabel = (h: Host) => (h.department_name ? `${h.name} — ${h.department_name}` : h.name);

/** Host filter: searched on the server as you type (the directory may be large). */
export function HostLookup({ value, onChange }: { value: string; onChange: (id: string) => void }) {
  const [query, setQuery] = useState("");
  const [options, setOptions] = useState<Option[]>([]);
  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(() => {
      listHosts({ q: query, includeInactive: true }, controller.signal)
        .then((hosts) => setOptions((prev) => {
          const found = uniqueOptions(hosts.map((h) => ({ id: h.id, label: hostLabel(h) })));
          const chosen = prev.find((o) => o.id === value);                 // keep the chosen host's label
          return chosen && !found.some((o) => o.id === chosen.id) ? [chosen, ...found] : found;
        }))
        .catch(() => { /* the field still works as plain text; the report shows its own errors */ });
    }, query ? 250 : 0);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [query, value]);
  return (
    <div onInput={(e) => setQuery((e.target as HTMLInputElement).value ?? "")}>
      <LookupField label="Host" options={options} value={value} onChange={onChange} placeholder="Any host" />
    </div>
  );
}

export function GateSelect({ gates, value, onChange }: { gates: Gate[]; value: string; onChange: (id: string) => void }) {
  return (
    <SelectField label="Gate" value={value} onChange={(e) => onChange(e.target.value)} caps>
      <option value="">Any gate</option>
      {gates.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
    </SelectField>
  );
}

export function DepartmentSelect({ departments, value, onChange }: {
  departments: Department[]; value: string; onChange: (id: string) => void;
}) {
  return (
    <SelectField label="Department" value={value} onChange={(e) => onChange(e.target.value)} caps>
      <option value="">Any department</option>
      {departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
    </SelectField>
  );
}

/** How many filters are set (for the narrow-screen "Filters (n)" button). */
export function countActive(filters: object, ignore: string[] = ["sort"]): number {
  return Object.entries(filters).filter(([k, v]) => !ignore.includes(k) && v !== undefined && v !== "").length;
}
