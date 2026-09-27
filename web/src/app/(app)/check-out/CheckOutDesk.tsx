"use client";

import { useCallback, useEffect, useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Modal } from "@/components/ui/Modal";
import { SelectField } from "@/components/ui/SelectField";
import { TextField } from "@/components/ui/TextField";
import { errorMessage } from "@/lib/api/client";
import { IDENTITY_LABELS, type IdentityType } from "@/lib/api/visitors";
import { activeVisits, checkOut, checkOutBy, type CheckOutResult, type Visit, VISIT_NUMBER_PATTERN } from "@/lib/api/visits";
import { formatDuration, formatTime } from "@/lib/format";

const REFRESH_MS = 30_000;

/** What the quick check-out box sends: a visit number when it looks like one, otherwise an ID number. */
export function checkOutTarget(value: string, idType: IdentityType) {
  const text = value.trim();
  return VISIT_NUMBER_PATTERN.test(text)
    ? { visit_number: text.toUpperCase() }
    : { identity: { type: idType, number: text } };
}

function resultMessage({ visit, already_checked_out }: CheckOutResult): { tone: "ok" | "warn"; text: string } {
  if (already_checked_out) {
    return { tone: "warn", text: `${visit.visitor.name} (${visit.visit_number}) was already checked out at ${formatTime(visit.check_out_at)}.` };
  }
  return {
    tone: "ok",
    text: `${visit.visitor.name} (${visit.visit_number}) checked out. Time inside: ${formatDuration(visit.check_in_at, visit.check_out_at)}.`,
  };
}

export function CheckOutDesk() {
  const [visits, setVisits] = useState<Visit[] | null>(null);
  const [total, setTotal] = useState(0);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ tone: "ok" | "warn"; text: string } | null>(null);
  const [filter, setFilter] = useState("");
  const [confirming, setConfirming] = useState<Visit | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await activeVisits();
      setVisits(data.items);
      setTotal(data.total);
      setLoadError(null);
    } catch (e) {
      setLoadError(errorMessage(e));
    }
  }, []);

  useEffect(() => {
    // Initial load and periodic refresh: results are applied from the async callback.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
    const timer = setInterval(() => void load(), REFRESH_MS);
    return () => clearInterval(timer);
  }, [load]);

  function done(result: CheckOutResult) {
    setConfirming(null);
    setNotice(resultMessage(result));
    void load();
  }

  const needle = filter.trim().toLowerCase();
  const shown = visits?.filter((v) => !needle || [v.visitor.name, v.visit_number, v.host.name]
    .some((s) => s?.toLowerCase().includes(needle))) ?? [];

  return (
    <div className="space-y-6">
      <QuickCheckOut onDone={done} />
      <div aria-live="polite">{notice && <Alert tone={notice.tone}>{notice.text}</Alert>}</div>

      <Card title={`Visitors inside${visits ? ` (${total})` : ""}`}
            actions={<Button variant="secondary" onClick={() => void load()}>Refresh</Button>}>
        <div className="space-y-3">
          {loadError && <Alert tone="danger">{loadError}</Alert>}
          <TextField label="Filter" value={filter} onChange={(e) => setFilter(e.target.value)}
                     placeholder="Name, visit number or host" />
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs uppercase tracking-wide text-ink-muted">
                <tr>
                  <th scope="col" className="py-2 pr-3">Visitor</th>
                  <th scope="col" className="py-2 pr-3">Visit</th>
                  <th scope="col" className="py-2 pr-3">Host</th>
                  <th scope="col" className="py-2 pr-3">In since</th>
                  <th scope="col" className="py-2 pr-3">Gate</th>
                  <th scope="col" className="py-2"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {visits === null && !loadError && (
                  <tr><td colSpan={6} className="py-6 text-center text-ink-muted">Loading…</td></tr>
                )}
                {visits !== null && shown.length === 0 && (
                  <tr><td colSpan={6} className="py-6 text-center text-ink-muted">
                    {visits.length === 0 ? "Nobody is checked in." : "No visitor matches the filter."}
                  </td></tr>
                )}
                {shown.map((v) => (
                  <tr key={v.id} data-testid="active-visit">
                    <td className="py-2 pr-3 font-medium text-ink">{v.visitor.name}</td>
                    <td className="py-2 pr-3 font-mono">{v.visit_number}</td>
                    <td className="py-2 pr-3">
                      {v.host.name}
                      {v.host_unlisted && <span className="ml-1 text-xs text-warn">(not listed)</span>}
                    </td>
                    <td className="py-2 pr-3">
                      {formatTime(v.check_in_at)}
                      <span className="block text-xs text-ink-muted">{formatDuration(v.check_in_at)}</span>
                    </td>
                    <td className="py-2 pr-3">{v.gate.name}</td>
                    <td className="py-2 text-right">
                      <Button variant="secondary" aria-label={`Check out ${v.visitor.name} (${v.visit_number})`}
                              onClick={() => { setNotice(null); setConfirming(v); }}>Check out</Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </Card>

      <Modal open={confirming !== null} title="Check out visitor" onClose={() => setConfirming(null)}>
        {confirming && <ConfirmCheckOut visit={confirming} onDone={done} onCancel={() => setConfirming(null)} />}
      </Modal>
    </div>
  );
}

function QuickCheckOut({ onDone }: { onDone: (result: CheckOutResult) => void }) {
  const [value, setValue] = useState("");
  const [idType, setIdType] = useState<IdentityType>("CNIC");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    if (!value.trim()) return setError("Enter a visit number or the visitor's ID number.");
    setSaving(true);
    try {
      onDone(await checkOutBy(checkOutTarget(value, idType)));
      setValue("");
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card title="Quick check-out" description="Type or scan the visit number from the pass, or enter the visitor's ID number.">
      <form onSubmit={onSubmit} noValidate className="grid items-start gap-3 sm:grid-cols-[1fr_10rem_auto]">
        <TextField label="Visit number or ID number" value={value} onChange={(e) => setValue(e.target.value)}
                   placeholder="V-2026-000123" autoComplete="off" spellCheck={false} autoFocus error={error ?? undefined} />
        <SelectField label="ID type (if not a visit number)" value={idType}
                     onChange={(e) => setIdType(e.target.value as IdentityType)}>
          {(Object.keys(IDENTITY_LABELS) as IdentityType[]).map((t) => <option key={t} value={t}>{IDENTITY_LABELS[t]}</option>)}
        </SelectField>
        <Button type="submit" loading={saving} className="sm:mt-6">Check out</Button>
      </form>
    </Card>
  );
}

function ConfirmCheckOut({ visit, onDone, onCancel }: {
  visit: Visit;
  onDone: (result: CheckOutResult) => void;
  onCancel: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function confirm() {
    setError(null);
    setSaving(true);
    try {
      onDone(await checkOut(visit.id));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-4">
      {error && <Alert tone="danger">{error}</Alert>}
      <p className="text-sm text-ink">
        Check out <strong>{visit.visitor.name}</strong> ({visit.visit_number}), visiting {visit.host.name}, inside since{" "}
        {formatTime(visit.check_in_at)}?
      </p>
      {visit.belongings.length > 0 && (
        <Alert tone="info">Belongings recorded at entry: {visit.belongings.join(", ")}.</Alert>
      )}
      <div className="flex justify-end gap-2">
        <Button variant="secondary" onClick={onCancel}>Cancel</Button>
        <Button onClick={() => void confirm()} loading={saving} autoFocus>Confirm check-out</Button>
      </div>
    </div>
  );
}
