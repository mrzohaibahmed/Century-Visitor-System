"use client";

import { useCallback, useEffect, useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { SelectField } from "@/components/ui/SelectField";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { TextField } from "@/components/ui/TextField";
import { errorMessage, fieldErrors } from "@/lib/api/client";
import {
  createEntry,
  type Department,
  type DirectoryKind,
  type Gate,
  type Host,
  listDepartments,
  listGates,
  listHosts,
  updateEntry,
} from "@/lib/api/directory";
import { listUsers } from "@/lib/api/users";
import { caps } from "@/lib/format";
import type { User } from "@/lib/api/auth";

type Entry = Gate | Department | Host;
type Field = { name: string; label: string; type?: "text" | "email" | "tel" | "department"; required?: boolean; hint?: string };

const CONFIG: Record<DirectoryKind, { singular: string; fields: Field[] }> = {
  gates: {
    singular: "gate",
    fields: [{ name: "name", label: "Name", required: true }, { name: "location", label: "Location" }],
  },
  departments: {
    singular: "department",
    fields: [
      { name: "name", label: "Name", required: true },
      { name: "notification_email", label: "Notification email", type: "email",
        hint: "Optional. Receives an e-mail whenever a visitor checks in to this department." },
    ],
  },
  hosts: {
    singular: "host",
    fields: [
      { name: "name", label: "Full name", required: true },
      { name: "department_id", label: "Department", type: "department" },
      { name: "email", label: "Email", type: "email" },
      { name: "phone", label: "Phone", type: "tel" },
    ],
  },
};

function load(kind: DirectoryKind): Promise<Entry[]> {
  if (kind === "gates") return listGates(true);
  if (kind === "departments") return listDepartments(true);
  return listHosts({ includeInactive: true });
}

function valueOf(entry: Entry | null, field: string): string {
  const value = entry ? (entry as Record<string, unknown>)[field] : null;
  return typeof value === "string" ? value : "";
}

/** The second column. Location and department are shown in capitals; emails, phones and user names keep their form. */
function secondary(kind: DirectoryKind, e: Entry): React.ReactNode {
  if (kind === "gates") return (e as Gate).location ? <span className="caps">{(e as Gate).location}</span> : "";
  if (kind === "departments") return (e as Department).notification_email ?? "";
  const h = e as Host;
  const rest = [h.email, h.phone, h.linked_user && `App: ${h.linked_user.name}`].filter(Boolean).join(" · ");
  if (!h.department_name && !rest) return "";
  return (
    <>
      {h.department_name && <span className="caps">{h.department_name}</span>}
      {h.department_name && rest && " · "}
      {rest}
    </>
  );
}

export function DirectoryManager({ kind }: { kind: DirectoryKind }) {
  const config = CONFIG[kind];
  const [entries, setEntries] = useState<Entry[] | null>(null);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [editing, setEditing] = useState<Entry | "new" | null>(null);

  const reload = useCallback(async () => {
    try {
      setEntries(await load(kind));
      setError(null);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [kind]);

  useEffect(() => {
    // Initial load: results are applied from the async callbacks.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void reload();
    if (kind === "hosts") {
      listDepartments(false).then(setDepartments).catch(() => {});
      listUsers().then((r) => setUsers(r.items.filter((u) => u.is_active))).catch(() => {});
    }
  }, [kind, reload]);

  const needle = filter.trim().toLowerCase();
  const shown = entries?.filter((e) => !needle || e.name.toLowerCase().includes(needle)) ?? [];

  return (
    <div className="space-y-4">
      <div className="flex items-end justify-between gap-4">
        <TextField label="Filter" className="w-72" value={filter} onChange={(e) => setFilter(e.target.value)} />
        <Button onClick={() => { setNotice(null); setEditing("new"); }}>New {config.singular}</Button>
      </div>
      <div aria-live="polite">{notice && <Alert tone="ok">{notice}</Alert>}</div>
      {error && <Alert tone="danger">{error}</Alert>}

      <div className="overflow-hidden rounded-xl border border-border bg-surface shadow-sm">
        <table className="w-full text-left text-sm">
          <thead className="bg-canvas text-xs uppercase tracking-wide text-ink-muted">
            <tr>
              <th scope="col" className="px-4 py-3">Name</th>
              <th scope="col" className="px-4 py-3">Details</th>
              <th scope="col" className="px-4 py-3">Status</th>
              <th scope="col" className="px-4 py-3"><span className="sr-only">Actions</span></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {entries === null && !error && <tr><td colSpan={4} className="px-4 py-8 text-center text-ink-muted">Loading…</td></tr>}
            {entries !== null && shown.length === 0 && (
              <tr><td colSpan={4} className="px-4 py-8 text-center text-ink-muted">Nothing here yet.</td></tr>
            )}
            {shown.map((e) => (
              <tr key={e.id}>
                <td className="caps px-4 py-3 font-medium text-ink">{e.name}</td>
                <td className="px-4 py-3 text-ink-muted">{secondary(kind, e) || "—"}</td>
                <td className="px-4 py-3">
                  {e.is_active ? <StatusBadge tone="ok">Active</StatusBadge> : <StatusBadge tone="neutral">Inactive</StatusBadge>}
                </td>
                <td className="px-4 py-3 text-right">
                  <Button variant="ghost" onClick={() => { setNotice(null); setEditing(e); }}>Edit</Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Modal open={editing !== null} title={editing === "new" ? `New ${config.singular}` : `Edit ${config.singular}`}
             onClose={() => setEditing(null)}>
        {editing !== null && (
          <EntryForm kind={kind} entry={editing === "new" ? null : editing} departments={departments} users={users}
                     onCancel={() => setEditing(null)}
                     onDone={(saved, created) => {
                       setEditing(null);
                       setNotice(`${caps(saved.name)} ${created ? "added" : "updated"}.`);
                       void reload();
                     }} />
        )}
      </Modal>
    </div>
  );
}

export function EntryForm({ kind, entry, departments, users = [], onDone, onCancel }: {
  kind: DirectoryKind;
  entry: Entry | null;
  departments: Department[];
  /** Active app accounts, for a host's optional "Linked app account". */
  users?: User[];
  onDone: (saved: Entry, created: boolean) => void;
  onCancel: () => void;
}) {
  const fields = CONFIG[kind].fields;
  const [values, setValues] = useState<Record<string, string>>(
    Object.fromEntries(fields.map((f) => [f.name, valueOf(entry, f.name)])));
  const [active, setActive] = useState(entry?.is_active ?? true);
  const initialLink = (entry as Host | null)?.linked_user?.id ?? "";
  const [linkedUser, setLinkedUser] = useState(initialLink);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    const missing = fields.filter((f) => f.required && !values[f.name].trim());
    if (missing.length) return setErrors(Object.fromEntries(missing.map((f) => [f.name, `${f.label} is required.`])));
    setErrors({});

    const body: Record<string, unknown> = {};
    for (const f of fields) {
      const value = values[f.name].trim();
      // Only send what changed; empty optional fields are left out (the API keeps the existing value).
      if (value && value !== valueOf(entry, f.name)) body[f.name] = value;
    }
    if (entry && active !== entry.is_active) body.is_active = active;
    if (kind === "hosts" && linkedUser !== initialLink) {
      if (linkedUser) body.linked_user_id = linkedUser;
      else body.clear_linked_user = true;
    }
    if (entry && Object.keys(body).length === 0) return onCancel();

    setSaving(true);
    try {
      const saved = entry ? await updateEntry<Entry>(kind, entry.id, body) : await createEntry<Entry>(kind, body);
      onDone(saved, !entry);
    } catch (e) {
      const byField = fieldErrors(e);
      if (Object.keys(byField).length) setErrors(byField);
      setError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={onSubmit} noValidate className="space-y-4">
      {error && <Alert tone="danger">{errors._form ?? error}</Alert>}
      {fields.map((f) => f.type === "department" ? (
        <SelectField key={f.name} label={f.label} value={values[f.name]} error={errors[f.name]} caps
                     onChange={(e) => setValues({ ...values, [f.name]: e.target.value })}>
          <option value="">{entry ? "(unchanged)" : "None"}</option>
          {departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
        </SelectField>
      ) : (
        <TextField key={f.name} label={f.label} type={f.type ?? "text"} value={values[f.name]} error={errors[f.name]}
                   hint={f.hint} caps={f.name === "name" || f.name === "location"}
                   onChange={(e) => setValues({ ...values, [f.name]: e.target.value })} />
      ))}
      {kind === "hosts" && (
        <SelectField label="Linked app account" value={linkedUser} error={errors.linked_user_id}
                     hint="Optional. This app user sees the host's visitor arrivals under the bell. The host does not log in."
                     onChange={(e) => setLinkedUser(e.target.value)}>
          <option value="">None</option>
          {initialLink && !users.some((u) => u.id === initialLink) && (
            <option value={initialLink}>{(entry as Host).linked_user?.name}</option>
          )}
          {users.map((u) => <option key={u.id} value={u.id}>{u.display_name || u.username} ({u.username})</option>)}
        </SelectField>
      )}
      {entry && (
        <label className="flex items-center gap-2 text-sm text-ink">
          <input type="checkbox" className="size-4" checked={active} onChange={(e) => setActive(e.target.checked)} />
          Active (shown in pickers at the gate)
        </label>
      )}
      {entry && entry.is_active && !active && (
        <Alert tone="warn">Inactive entries are hidden from new check-ins. Past visits keep their records.</Alert>
      )}
      <div className="flex justify-end gap-2">
        <Button type="button" variant="secondary" onClick={onCancel}>Cancel</Button>
        <Button type="submit" loading={saving}>{entry ? "Save changes" : "Add"}</Button>
      </div>
    </form>
  );
}
