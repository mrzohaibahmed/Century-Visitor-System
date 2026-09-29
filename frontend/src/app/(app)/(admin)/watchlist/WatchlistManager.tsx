"use client";

import { useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { SelectField } from "@/components/ui/SelectField";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { TextField } from "@/components/ui/TextField";
import { IdentityInput } from "@/components/visits/IdentityInput";
import { usePagedList } from "@/hooks/usePagedList";
import { errorMessage, fieldErrors } from "@/lib/api/client";
import { IDENTITY_LABELS, type IdentityType } from "@/lib/api/visitors";
import {
  addWatchlistEntry,
  disableWatchlistEntry,
  endOfDayIso,
  expireWatchlistEntry,
  listWatchlist,
  updateWatchlistEntry,
  type WatchlistChanges,
  type WatchlistEntry,
  type WatchlistStatus,
} from "@/lib/api/watchlist";
import { caps, formatDateTime, isoDay } from "@/lib/format";

type Filters = { q: string; status: WatchlistStatus | "" };
type Action = { kind: "new" } | { kind: "edit" | "expire" | "disable"; entry: WatchlistEntry };

const STATUS: Record<WatchlistStatus, { tone: "danger" | "neutral" | "warn"; label: string }> = {
  ACTIVE: { tone: "danger", label: "Active" },
  EXPIRED: { tone: "warn", label: "Expired" },
  DISABLED: { tone: "neutral", label: "Disabled" },
};

const TITLES: Record<Action["kind"], string> = {
  new: "Add to watchlist", edit: "Edit watchlist entry", expire: "Expire entry now", disable: "Disable entry",
};

export function WatchlistManager() {
  const [draft, setDraft] = useState<Filters>({ q: "", status: "ACTIVE" });
  const [applied, setApplied] = useState<Filters>(draft);
  const [action, setAction] = useState<Action | null>(null);
  const [notice, setNotice] = useState<{ tone: "ok" | "warn"; text: string } | null>(null);
  const list = usePagedList(JSON.stringify(applied), (cursor) => listWatchlist(applied, cursor));

  function onSearch(event: React.FormEvent) {
    event.preventDefault();
    if (JSON.stringify(draft) === JSON.stringify(applied)) list.reload();
    else setApplied({ ...draft });
  }

  function done(text: string, tone: "ok" | "warn" = "ok") {
    setAction(null);
    setNotice({ tone, text });
    list.reload();
  }

  const open = (next: Action) => { setNotice(null); setAction(next); };

  return (
    <div className="space-y-4">
      <form onSubmit={onSearch} className="grid items-end gap-3 rounded-xl border border-border bg-surface p-4 shadow-sm sm:grid-cols-[1fr_12rem_auto_auto]">
        <TextField label="Search watchlist" value={draft.q} onChange={(e) => setDraft({ ...draft, q: e.target.value })}
                   placeholder="ID number or name" autoComplete="off" spellCheck={false} />
        <SelectField label="Status" value={draft.status}
                     onChange={(e) => setDraft({ ...draft, status: e.target.value as Filters["status"] })}>
          <option value="ACTIVE">Active</option>
          <option value="EXPIRED">Expired</option>
          <option value="DISABLED">Disabled</option>
          <option value="">All</option>
        </SelectField>
        <Button type="submit" variant="secondary">Search</Button>
        <Button type="button" onClick={() => open({ kind: "new" })}>Add to watchlist</Button>
      </form>
      <div aria-live="polite">{notice && <Alert tone={notice.tone}>{notice.text}</Alert>}</div>
      {list.error && <Alert tone="danger">{list.error}</Alert>}

      <div className="overflow-x-auto rounded-xl border border-border bg-surface shadow-sm">
        <table className="w-full text-left text-sm">
          <thead className="bg-canvas text-xs uppercase tracking-wide text-ink-muted">
            <tr>
              <th scope="col" className="px-4 py-3">Person</th>
              <th scope="col" className="px-4 py-3">Reason</th>
              <th scope="col" className="px-4 py-3">Status</th>
              <th scope="col" className="px-4 py-3">Added</th>
              <th scope="col" className="px-4 py-3">Ends</th>
              <th scope="col" className="px-4 py-3"><span className="sr-only">Actions</span></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {list.loading && list.items.length === 0 && (
              <tr><td colSpan={6} className="px-4 py-8 text-center text-ink-muted">Loading…</td></tr>
            )}
            {!list.loading && list.items.length === 0 && !list.error && (
              <tr><td colSpan={6} className="px-4 py-8 text-center text-ink-muted">No entries match.</td></tr>
            )}
            {list.items.map((e) => (
              <tr key={e.id} data-testid="watchlist-row" className="align-top">
                <td className="px-4 py-3">
                  <p className="caps font-medium text-ink">{e.name ?? "—"}</p>
                  <p className="font-mono text-xs text-ink-muted">{IDENTITY_LABELS[e.identity.type]} {e.identity.number}</p>
                </td>
                <td className="max-w-xs px-4 py-3 text-ink">
                  {e.reason}
                  {e.status === "DISABLED" && e.disabled_reason && (
                    <p className="mt-1 text-xs text-ink-muted">
                      Disabled {formatDateTime(e.disabled_at)}{e.disabled_by?.name ? ` by ${e.disabled_by.name}` : ""}: {e.disabled_reason}
                    </p>
                  )}
                </td>
                <td className="px-4 py-3"><StatusBadge tone={STATUS[e.status].tone}>{STATUS[e.status].label}</StatusBadge></td>
                <td className="px-4 py-3 text-ink-muted">
                  {formatDateTime(e.created_at)}
                  <span className="block text-xs">by {e.created_by.name ?? "—"}</span>
                </td>
                <td className="px-4 py-3 text-ink-muted">{e.expires_at ? formatDateTime(e.expires_at) : "No end date"}</td>
                <td className="whitespace-nowrap px-4 py-3 text-right">
                  {e.status !== "DISABLED" && (
                    <>
                      <Button variant="ghost" aria-label={`Edit ${e.name ?? e.identity.number}`}
                              onClick={() => open({ kind: "edit", entry: e })}>Edit</Button>
                      {e.status === "ACTIVE" && (
                        <Button variant="ghost" aria-label={`Expire ${e.name ?? e.identity.number}`}
                                onClick={() => open({ kind: "expire", entry: e })}>Expire</Button>
                      )}
                      <Button variant="ghost" aria-label={`Disable ${e.name ?? e.identity.number}`}
                              onClick={() => open({ kind: "disable", entry: e })}>Disable</Button>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {list.hasMore && (
        <div className="flex justify-center">
          <Button variant="secondary" onClick={list.loadMore} loading={list.loading}>Load more</Button>
        </div>
      )}

      <Modal open={action !== null} title={action ? TITLES[action.kind] : ""} onClose={() => setAction(null)}>
        {action?.kind === "new" && (
          <AddEntryForm onCancel={() => setAction(null)}
                        onDone={(created) => created.inside_visit_number
                          ? done(`${created.name ? caps(created.name) : "The person"} added to the watchlist. They are INSIDE now (visit ${created.inside_visit_number}): inform security.`, "warn")
                          : done(`${created.name ? caps(created.name) : created.identity.number} added to the watchlist.`)} />
        )}
        {action?.kind === "edit" && (
          <EditEntryForm entry={action.entry} onCancel={() => setAction(null)} onDone={() => done("Watchlist entry updated.")} />
        )}
        {(action?.kind === "expire" || action?.kind === "disable") && (
          <EndEntryForm kind={action.kind} entry={action.entry} onCancel={() => setAction(null)}
                        onDone={() => done(action.kind === "expire" ? "Entry expired. It no longer blocks entry."
                          : "Entry disabled. It no longer blocks entry.")} />
        )}
      </Modal>
    </div>
  );
}

function FormError({ error }: { error: string | null }) {
  return error ? <Alert tone="danger">{error}</Alert> : null;
}

export function AddEntryForm({ onDone, onCancel }: {
  onDone: (created: Awaited<ReturnType<typeof addWatchlistEntry>>) => void;
  onCancel: () => void;
}) {
  const [idType, setIdType] = useState<IdentityType>("CNIC");
  const [idNumber, setIdNumber] = useState("");
  const [name, setName] = useState("");
  const [reason, setReason] = useState("");
  const [until, setUntil] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    const missing: Record<string, string> = {};
    if (!idNumber.trim()) missing.identity = "Enter the ID number.";
    if (reason.trim().length < 3) missing.reason = "Describe the reason (at least 3 characters).";
    setErrors(missing);
    if (Object.keys(missing).length) return;
    setSaving(true);
    try {
      onDone(await addWatchlistEntry({
        identity: { type: idType, number: idNumber }, name: name.trim() || null, reason: reason.trim(),
        expires_at: until ? endOfDayIso(until) : null,
      }));
    } catch (e) {
      const byField = fieldErrors(e);
      setErrors(byField);
      setError(Object.keys(byField).length ? byField._form ?? null : errorMessage(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={onSubmit} noValidate className="space-y-4">
      <FormError error={error} />
      <IdentityInput type={idType} number={idNumber} onType={setIdType} onNumber={setIdNumber} error={errors.identity} autoFocus />
      <TextField label="Name (optional)" value={name} onChange={(e) => setName(e.target.value)} error={errors.name} caps
                 hint="Filled in from the visitor record if this person is registered." autoComplete="off" />
      <ReasonField value={reason} onChange={setReason} error={errors.reason} />
      <TextField label="Ends on (optional)" type="date" value={until} min={isoDay()} onChange={(e) => setUntil(e.target.value)}
                 error={errors.expires_at} hint="Leave empty for no end date." />
      <div className="flex justify-end gap-2">
        <Button type="button" variant="secondary" onClick={onCancel}>Cancel</Button>
        <Button type="submit" variant="danger" loading={saving}>Add to watchlist</Button>
      </div>
    </form>
  );
}

function ReasonField({ value, onChange, error }: { value: string; onChange: (v: string) => void; error?: string }) {
  return (
    <div>
      <label htmlFor="watchlist-reason" className="mb-1 block text-sm font-medium text-ink">Reason</label>
      <textarea id="watchlist-reason" value={value} onChange={(e) => onChange(e.target.value)} rows={3} maxLength={500}
                aria-invalid={error ? true : undefined} aria-describedby="watchlist-reason-hint"
                className={`block w-full rounded-lg border bg-surface px-3 py-2 text-base text-ink ${error ? "border-danger" : "border-border"}`} />
      {error
        ? <p id="watchlist-reason-hint" className="mt-1 text-sm text-danger">{error}</p>
        : <p id="watchlist-reason-hint" className="mt-1 text-xs text-ink-muted">Shown to the guard when this person is refused entry.</p>}
    </div>
  );
}

export function EditEntryForm({ entry, onDone, onCancel }: {
  entry: WatchlistEntry;
  onDone: () => void;
  onCancel: () => void;
}) {
  const initialUntil = entry.expires_at ? isoDay(new Date(entry.expires_at)) : "";
  const [name, setName] = useState(entry.name ?? "");
  const [reason, setReason] = useState(entry.reason);
  const [until, setUntil] = useState(initialUntil);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    const changes: WatchlistChanges = {};
    if (name.trim() && name.trim() !== (entry.name ?? "")) changes.name = name.trim();
    if (reason.trim() !== entry.reason) changes.reason = reason.trim();
    if (until !== initialUntil) {
      if (until) changes.expires_at = endOfDayIso(until);
      else changes.clear_expiry = true;
    }
    if (Object.keys(changes).length === 0) return onCancel();
    setSaving(true);
    try {
      await updateWatchlistEntry(entry.id, changes);
      onDone();
    } catch (e) {
      const byField = fieldErrors(e);
      setErrors(byField);
      setError(Object.keys(byField).length ? byField._form ?? null : errorMessage(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={onSubmit} noValidate className="space-y-4">
      <FormError error={error} />
      <p className="text-sm">
        <span className="text-ink-muted">{IDENTITY_LABELS[entry.identity.type]}: </span>
        <span className="font-mono font-semibold text-ink">{entry.identity.number}</span>
      </p>
      <p className="text-xs text-ink-muted">The ID number cannot be changed. If it is wrong, disable this entry and add a new one.</p>
      <TextField label="Name" value={name} onChange={(e) => setName(e.target.value)} error={errors.name} autoComplete="off" caps />
      <ReasonField value={reason} onChange={setReason} error={errors.reason} />
      <TextField label="Ends on" type="date" value={until} min={isoDay()} onChange={(e) => setUntil(e.target.value)}
                 error={errors.expires_at} hint="Clear the date for no end date." />
      <div className="flex justify-end gap-2">
        <Button type="button" variant="secondary" onClick={onCancel}>Cancel</Button>
        <Button type="submit" loading={saving}>Save changes</Button>
      </div>
    </form>
  );
}

export function EndEntryForm({ kind, entry, onDone, onCancel }: {
  kind: "expire" | "disable";
  entry: WatchlistEntry;
  onDone: () => void;
  onCancel: () => void;
}) {
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [noteError, setNoteError] = useState<string | undefined>();
  const [saving, setSaving] = useState(false);

  async function confirm(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    if (kind === "disable" && note.trim().length < 3) return setNoteError("Say why the ban is lifted (at least 3 characters).");
    setSaving(true);
    try {
      if (kind === "expire") await expireWatchlistEntry(entry.id);
      else await disableWatchlistEntry(entry.id, note.trim());
      onDone();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={confirm} noValidate className="space-y-4">
      <FormError error={error} />
      <p className="text-sm text-ink">
        <strong className={entry.name ? "caps" : undefined}>{entry.name ?? entry.identity.number}</strong> ({IDENTITY_LABELS[entry.identity.type]} {entry.identity.number})
        will no longer be blocked at the gate.{" "}
        {kind === "expire" ? "The entry is kept, marked as expired now." : "The entry is kept, marked as disabled, and can no longer be edited."}
      </p>
      {kind === "disable" && (
        <TextField label="Why is the ban lifted?" value={note} onChange={(e) => setNote(e.target.value)} error={noteError}
                   maxLength={200} autoFocus />
      )}
      <div className="flex justify-end gap-2">
        <Button type="button" variant="secondary" onClick={onCancel}>Cancel</Button>
        <Button type="submit" loading={saving}>{kind === "expire" ? "Expire now" : "Disable entry"}</Button>
      </div>
    </form>
  );
}
