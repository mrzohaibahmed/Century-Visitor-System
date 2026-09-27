"use client";

import { useCallback, useEffect, useState } from "react";

import { BadgePreview } from "@/components/badge/VisitorBadge";
import { QrScanner } from "@/components/scan/QrScanner";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Modal } from "@/components/ui/Modal";
import { SelectField } from "@/components/ui/SelectField";
import { TextField } from "@/components/ui/TextField";
import { VisitorPhoto } from "@/components/visits/VisitorPhoto";
import { errorMessage } from "@/lib/api/client";
import { checkOutWithPass, type IssuedPass, issuePass, looksLikePass, resolvePass, type ScanResult } from "@/lib/api/passes";
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
  const [scanning, setScanning] = useState(false);
  const [scanned, setScanned] = useState<{ qrText: string; result: ScanResult } | null>(null);
  const [scanError, setScanError] = useState<string | null>(null);
  const [reissuing, setReissuing] = useState<Visit | null>(null);

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
    setScanned(null);
    setNotice(resultMessage(result));
    void load();
  }

  /** A pass read by the camera or typed by a USB scanner: look it up, then ask the guard to confirm. */
  async function passScanned(qrText: string) {
    setScanning(false);
    setNotice(null);
    setScanError(null);
    try {
      setScanned({ qrText, result: await resolvePass(qrText) });
    } catch (e) {
      setScanError(errorMessage(e));
    }
  }

  const needle = filter.trim().toLowerCase();
  const shown = visits?.filter((v) => !needle || [v.visitor.name, v.visit_number, v.host.name]
    .some((s) => s?.toLowerCase().includes(needle))) ?? [];

  return (
    <div className="space-y-6">
      <QuickCheckOut onDone={done} onPass={passScanned}
                     onScanWithCamera={() => { setNotice(null); setScanError(null); setScanning(true); }} />
      <div aria-live="polite">
        {notice && <Alert tone={notice.tone}>{notice.text}</Alert>}
        {scanError && <Alert tone="danger">{scanError}</Alert>}
      </div>

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
                    <td className="whitespace-nowrap py-2 text-right">
                      <Button variant="ghost" aria-label={`Reprint badge for ${v.visitor.name} (${v.visit_number})`}
                              onClick={() => { setNotice(null); setReissuing(v); }}>Badge</Button>
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

      <Modal open={scanning} title="Scan visitor badge" onClose={() => setScanning(false)}>
        {scanning && <QrScanner onScan={(text) => void passScanned(text)} onCancel={() => setScanning(false)} />}
      </Modal>

      <Modal open={scanned !== null} title="Check out visitor" onClose={() => setScanned(null)}>
        {scanned && <ConfirmPassCheckOut scan={scanned.result} qrText={scanned.qrText} onDone={done}
                                         onCancel={() => setScanned(null)} />}
      </Modal>

      <Modal open={reissuing !== null} title="Reprint badge" onClose={() => setReissuing(null)}>
        {reissuing && <ReissueBadge visit={reissuing} onClose={() => setReissuing(null)} />}
      </Modal>
    </div>
  );
}

function QuickCheckOut({ onDone, onPass, onScanWithCamera }: {
  onDone: (result: CheckOutResult) => void;
  onPass: (qrText: string) => Promise<void>;
  onScanWithCamera: () => void;
}) {
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
      if (looksLikePass(value)) {
        // A USB QR scanner "types" the badge's code: look it up and confirm, never check out directly.
        await onPass(value.trim());
        setValue("");
        return;
      }
      onDone(await checkOutBy(checkOutTarget(value, idType)));
      setValue("");
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card title="Quick check-out" description="Scan the QR code on the visitor's badge, type the visit number, or enter the visitor's ID number."
          actions={<Button variant="secondary" onClick={onScanWithCamera}>Scan badge with camera</Button>}>
      <form onSubmit={onSubmit} noValidate className="grid items-start gap-3 sm:grid-cols-[1fr_10rem_auto]">
        <TextField label="Visit number or ID number" value={value} onChange={(e) => setValue(e.target.value)}
                   hint="A USB badge scanner can scan into this box."
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

function VisitSummary({ visit }: { visit: Visit }) {
  return (
    <div className="flex gap-4">
      <VisitorPhoto photoId={visit.photo_id} name={visit.visitor.name} />
      <dl className="space-y-1 text-sm">
        <div><dt className="sr-only">Visitor</dt><dd className="text-base font-semibold text-ink" data-testid="scanned-visitor">{visit.visitor.name}</dd></div>
        <div><dt className="sr-only">Visit</dt><dd className="font-mono">{visit.visit_number}</dd></div>
        <div><dt className="inline text-ink-muted">Visiting: </dt><dd className="inline">{visit.host.name}{visit.department.name ? ` (${visit.department.name})` : ""}</dd></div>
        <div><dt className="inline text-ink-muted">Inside since: </dt><dd className="inline">{formatTime(visit.check_in_at)} · {visit.gate.name}</dd></div>
      </dl>
    </div>
  );
}

export function ConfirmPassCheckOut({ scan, qrText, onDone, onCancel }: {
  scan: ScanResult;
  qrText: string;
  onDone: (result: CheckOutResult) => void;
  onCancel: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const { visit } = scan;

  async function confirm() {
    setError(null);
    setSaving(true);
    try {
      onDone(await checkOutWithPass(qrText));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-4" data-testid="scan-confirm">
      {error && <Alert tone="danger">{error}</Alert>}
      <VisitSummary visit={visit} />
      {scan.status === "CHECKED_OUT" ? (
        <>
          <Alert tone="warn">This badge belongs to a visit that was already checked out at {formatTime(visit.check_out_at)}. Nothing was changed.</Alert>
          <div className="flex justify-end"><Button onClick={onCancel} autoFocus>Close</Button></div>
        </>
      ) : (
        <>
          <p className="text-sm text-ink">Check that the person in front of you matches the photo, then confirm.</p>
          {visit.belongings.length > 0 && (
            <Alert tone="info">Belongings recorded at entry: {visit.belongings.join(", ")}.</Alert>
          )}
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={onCancel}>Cancel</Button>
            <Button onClick={() => void confirm()} loading={saving} autoFocus>Confirm check-out</Button>
          </div>
        </>
      )}
    </div>
  );
}

/** Lost or damaged badge: a new pass is issued and the old QR stops working at once. */
function ReissueBadge({ visit, onClose }: { visit: Visit; onClose: () => void }) {
  const [issued, setIssued] = useState<IssuedPass | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function reissue() {
    setError(null);
    setSaving(true);
    try {
      setIssued(await issuePass(visit.id));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  }

  if (issued) {
    return (
      <div className="space-y-4">
        <Alert tone="ok">New badge ready. The previous badge no longer works.</Alert>
        <BadgePreview issued={issued} visitId={visit.id} />
        <div className="flex justify-end"><Button variant="secondary" onClick={onClose}>Close</Button></div>
      </div>
    );
  }
  return (
    <div className="space-y-4">
      {error && <Alert tone="danger">{error}</Alert>}
      <VisitSummary visit={visit} />
      <Alert tone="warn">Printing a new badge cancels the old one: its QR code will be refused at check-out.</Alert>
      <div className="flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button onClick={() => void reissue()} loading={saving}>Issue new badge</Button>
      </div>
    </div>
  );
}
