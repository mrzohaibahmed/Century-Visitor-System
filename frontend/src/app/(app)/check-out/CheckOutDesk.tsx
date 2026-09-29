"use client";

import { Check, LoaderCircle, LogOut, Printer, RefreshCw, ScanLine, UserRoundX } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { BadgePreview } from "@/components/badge/VisitorBadge";
import { QrScanner } from "@/components/scan/QrScanner";
import { Alert } from "@/components/ui/Alert";
import { Avatar } from "@/components/ui/Avatar";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Modal } from "@/components/ui/Modal";
import { SelectField } from "@/components/ui/SelectField";
import { Skeleton } from "@/components/ui/Skeleton";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { TextField } from "@/components/ui/TextField";
import { VisitorPhoto } from "@/components/visits/VisitorPhoto";
import { errorMessage } from "@/lib/api/client";
import { checkOutWithPass, type IssuedPass, issuePass, looksLikePass, resolvePass, type ScanResult } from "@/lib/api/passes";
import { IDENTITY_LABELS, type IdentityType } from "@/lib/api/visitors";
import { activeVisits, checkOut, checkOutBy, type CheckOutResult, type Visit, VISIT_NUMBER_PATTERN } from "@/lib/api/visits";
import { caps, formatDuration, formatTime } from "@/lib/format";

import { isLongStay } from "../dashboard/useDashboardData";

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
    return { tone: "warn", text: `${caps(visit.visitor.name)} (${visit.visit_number}) was already checked out at ${formatTime(visit.check_out_at)}.` };
  }
  return {
    tone: "ok",
    text: `${caps(visit.visitor.name)} (${visit.visit_number}) checked out. Time inside: ${formatDuration(visit.check_in_at, visit.check_out_at)}.`,
  };
}

/**
 * Check-out: find the visitor (camera scan, USB scanner or typed number, or the list of people
 * inside), confirm, done. A scanned badge is only looked up; nothing changes until the guard confirms.
 */
export function CheckOutDesk() {
  const [visits, setVisits] = useState<Visit[] | null>(null);
  const [total, setTotal] = useState(0);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<CheckOutResult | null>(null);
  const [filter, setFilter] = useState("");
  const [confirming, setConfirming] = useState<Visit | null>(null);
  const [scanning, setScanning] = useState(false);
  const [resolving, setResolving] = useState(false);
  const [scanned, setScanned] = useState<{ qrText: string; result: ScanResult } | null>(null);
  const [scanError, setScanError] = useState<string | null>(null);
  const [reissuing, setReissuing] = useState<Visit | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [focusFind, setFocusFind] = useState(0);
  const [now, setNow] = useState<number | null>(null);

  const load = useCallback(async () => {
    setRefreshing(true);
    try {
      const data = await activeVisits();
      setVisits(data.items);
      setTotal(data.total);
      setLoadError(null);
      setNow(Date.now());
    } catch (e) {
      setLoadError(errorMessage(e));
    } finally {
      setRefreshing(false);
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
    setOutcome(result);
    void load();
  }

  function clearMessages() {
    setOutcome(null);
    setScanError(null);
  }

  /** A pass read by the camera or typed by a USB scanner: look it up, then ask the guard to confirm. */
  async function passScanned(qrText: string) {
    setScanning(false);
    clearMessages();
    setResolving(true);
    try {
      setScanned({ qrText, result: await resolvePass(qrText) });
    } catch (e) {
      setScanError(errorMessage(e));
    } finally {
      setResolving(false);
    }
  }

  const needle = filter.trim().toLowerCase();
  const shown = visits?.filter((v) => !needle || [v.visitor.name, v.visit_number, v.host.name]
    .some((s) => s?.toLowerCase().includes(needle))) ?? [];

  return (
    <div className="space-y-6">
      <div aria-live="polite" className="space-y-3 empty:hidden">
        {resolving && (
          <p role="status" className="flex items-center gap-2 text-sm text-ink-muted">
            <LoaderCircle aria-hidden="true" className="size-4 animate-spin" />
            Looking up the badge…
          </p>
        )}
        {outcome && (outcome.already_checked_out
          ? <Alert tone="warn">{resultMessage(outcome).text}</Alert>
          : <CheckedOut result={outcome} onNext={() => { clearMessages(); setFocusFind((n) => n + 1); }} />)}
        {scanError && <Alert tone="danger" title="Badge not accepted">{scanError}</Alert>}
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)] lg:items-start">
        <FindVisitor focusKey={focusFind} onDone={done} onPass={passScanned} onStart={clearMessages}
                     onScanWithCamera={() => { clearMessages(); setScanning(true); }} />

        <section aria-labelledby="inside-heading" className="rounded-2xl border border-border bg-surface shadow-card">
          <header className="flex items-center justify-between gap-3 border-b border-border px-5 py-4 sm:px-6">
            <div className="flex min-w-0 items-center gap-2.5">
              <h2 id="inside-heading" className="text-heading text-ink">Visitors inside</h2>
              {visits && (
                <span className="rounded-full bg-surface-subtle px-2.5 py-0.5 text-sm font-semibold text-ink-muted tabular-nums">
                  {total}
                </span>
              )}
            </div>
            <Button variant="ghost" onClick={() => void load()} disabled={refreshing} className="shrink-0">
              <RefreshCw aria-hidden="true" className={refreshing ? "animate-spin" : ""} />
              Refresh
            </Button>
          </header>

          <div className="space-y-4 px-5 pt-4 sm:px-6">
            {loadError && (
              <Alert tone="danger" title={visits ? "Could not refresh the list" : "Unable to load visitors inside"}>
                <p>{loadError}</p>
                <button type="button" onClick={() => void load()} className="mt-1 font-semibold underline underline-offset-2">
                  Try again
                </button>
              </Alert>
            )}
            {(visits?.length ?? 0) > 0 && (
              <TextField label="Filter" value={filter} onChange={(e) => setFilter(e.target.value)}
                         placeholder="Name, visit number or host" autoComplete="off" />
            )}
          </div>

          {visits === null && !loadError && (
            <div role="status" className="space-y-4 px-5 py-5 sm:px-6">
              <span className="sr-only">Loading visitors inside…</span>
              {[0, 1, 2].map((i) => (
                <div key={i} className="flex items-center gap-3">
                  <Skeleton className="size-9 rounded-full" />
                  <Skeleton className="h-4 flex-1" />
                  <Skeleton className="h-9 w-28" />
                </div>
              ))}
            </div>
          )}

          {visits !== null && shown.length === 0 && (
            <div className="flex flex-col items-center gap-2 px-6 py-12 text-center">
              <span aria-hidden="true" className="flex size-12 items-center justify-center rounded-full bg-surface-subtle text-ink-muted">
                <UserRoundX className="size-6" />
              </span>
              <p className="font-semibold text-ink">{visits.length === 0 ? "Nobody is checked in." : "No visitor matches the filter."}</p>
              <p className="max-w-xs text-sm text-ink-muted">
                {visits.length === 0 ? "Visitors appear here after they check in." : "Check the spelling, or clear the filter."}
              </p>
            </div>
          )}

          {shown.length > 0 && (
            <>
              {/* One markup for every width (no duplicate rows): columns from md, cards below. */}
              <div aria-hidden="true" className="mt-4 hidden gap-4 border-y border-border px-6 py-2.5 text-xs font-medium text-ink-muted
                md:grid md:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)_11.5rem]">
                <span>Visitor</span><span>Host</span><span />
              </div>
              <ul aria-label="Visitors inside" className="mt-4 divide-y divide-border border-t border-border md:mt-0 md:border-t-0">
                {shown.map((v) => (
                  <li key={v.id} data-testid="active-visit"
                      className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-2 px-5 py-4 transition-colors hover:bg-surface-subtle
                        sm:px-6 md:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)_11.5rem] md:items-center md:gap-4">
                    <div className="col-span-2 flex min-w-0 items-start gap-3 md:col-span-1">
                      <Avatar name={v.visitor.name ?? ""} size="sm" />
                      <div className="min-w-0">
                        <p className="caps truncate font-semibold text-ink">{v.visitor.name}</p>
                        <p className="font-mono text-xs text-ink-muted">{v.visit_number}</p>
                        <p className="mt-1 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs text-ink-muted">
                          <span>In <span className="text-ink tabular-nums">{formatTime(v.check_in_at)}</span> · <span className="caps">{v.gate.name}</span></span>
                          <span aria-hidden="true">·</span>
                          <span className="tabular-nums">{formatDuration(v.check_in_at)}</span>
                          {now !== null && isLongStay(v, now) && <StatusBadge tone="warn">Long stay</StatusBadge>}
                        </p>
                      </div>
                    </div>
                    <div className="col-start-2 min-w-0 text-sm md:col-start-auto">
                      <span className="caps text-ink">{v.host.name}</span>
                      {v.host_unlisted && <span className="ml-1 text-xs font-medium text-warn">(not listed)</span>}
                      {v.department.name && <span className="caps block truncate text-xs text-ink-muted">{v.department.name}</span>}
                    </div>
                    <div className="col-span-2 grid grid-cols-2 gap-2 md:col-span-1 md:flex md:justify-end">
                      <Button variant="ghost" aria-label={`Reprint badge for ${v.visitor.name} (${v.visit_number})`}
                              title="Reprint badge" className="whitespace-nowrap md:w-11 md:shrink-0 md:px-0"
                              onClick={() => { clearMessages(); setReissuing(v); }}>
                        <Printer aria-hidden="true" />
                        <span className="md:hidden">Badge</span>
                      </Button>
                      <Button variant="secondary" aria-label={`Check out ${v.visitor.name} (${v.visit_number})`}
                              className="whitespace-nowrap" onClick={() => { clearMessages(); setConfirming(v); }}>
                        <LogOut aria-hidden="true" />
                        Check out
                      </Button>
                    </div>
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>
      </div>

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

/** The completed check-out, with the way on to the next visitor. */
function CheckedOut({ result, onNext }: { result: CheckOutResult; onNext: () => void }) {
  const { visit } = result;
  return (
    <section aria-labelledby="checked-out-heading"
             className="flex flex-col gap-4 rounded-2xl border border-ok/30 bg-ok-bg p-5 sm:flex-row sm:items-center">
      <span aria-hidden="true" className="flex size-12 shrink-0 animate-success-in items-center justify-center rounded-full bg-surface text-ok">
        <Check className="size-6" strokeWidth={3} />
      </span>
      <div className="min-w-0 flex-1">
        <h2 id="checked-out-heading" className="text-heading text-ink">Checked out</h2>
        <p className="text-ink">{resultMessage(result).text}</p>
        <p className="mt-0.5 text-sm text-ink-muted tabular-nums">
          In {formatTime(visit.check_in_at)} · Out {formatTime(visit.check_out_at)} · <span className="caps">{(visit.checkout_gate ?? visit.gate).name}</span>
        </p>
      </div>
      <Button size="lg" onClick={onNext} className="shrink-0">
        <ScanLine aria-hidden="true" />
        Check out next visitor
      </Button>
    </section>
  );
}

function FindVisitor({ focusKey, onDone, onPass, onStart, onScanWithCamera }: {
  focusKey: number;
  onDone: (result: CheckOutResult) => void;
  onPass: (qrText: string) => Promise<void>;
  onStart: () => void;
  onScanWithCamera: () => void;
}) {
  const [value, setValue] = useState("");
  const [idType, setIdType] = useState<IdentityType>("CNIC");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const form = useRef<HTMLFormElement>(null);

  useEffect(() => {
    // "Check out next visitor": ready for the next badge (a USB scanner types into this box).
    if (focusKey > 0) form.current?.querySelector("input")?.focus();
  }, [focusKey]);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    if (!value.trim()) return setError("Enter a visit number or the visitor's ID number.");
    onStart();
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
    <Card title="Find the visitor" description="Scan the QR code on the visitor's badge, or type the visit number."
          icon={<ScanLine />} divided={false}>
      <div className="space-y-5">
        <Button size="lg" className="w-full" onClick={onScanWithCamera}>
          <ScanLine aria-hidden="true" />
          Scan badge with camera
        </Button>
        <div aria-hidden="true" className="flex items-center gap-3 text-xs font-medium text-ink-subtle">
          <span className="h-px flex-1 bg-border" />or type it<span className="h-px flex-1 bg-border" />
        </div>
        <form ref={form} onSubmit={onSubmit} noValidate className="space-y-4">
          <TextField label="Visit number or ID number" value={value} onChange={(e) => setValue(e.target.value)} size="lg"
                     hint="A USB badge scanner can scan into this box."
                     placeholder="V-2026-000123" autoComplete="off" spellCheck={false} autoFocus error={error ?? undefined} />
          <SelectField label="ID type" value={idType} hint="Only used for an ID number, not a visit number."
                       onChange={(e) => setIdType(e.target.value as IdentityType)}>
            {(Object.keys(IDENTITY_LABELS) as IdentityType[]).map((t) => <option key={t} value={t}>{IDENTITY_LABELS[t]}</option>)}
          </SelectField>
          <Button type="submit" variant="secondary" size="lg" loading={saving} className="w-full">
            {!saving && <LogOut aria-hidden="true" />}
            Check out
          </Button>
        </form>
      </div>
    </Card>
  );
}

function ConfirmActions({ saving, onConfirm, onCancel }: { saving: boolean; onConfirm: () => void; onCancel: () => void }) {
  return (
    <div className="flex flex-col-reverse gap-3 pt-2 sm:flex-row sm:justify-end">
      <Button variant="secondary" size="lg" onClick={onCancel} disabled={saving}>Cancel</Button>
      <Button size="lg" onClick={onConfirm} loading={saving} autoFocus>
        {!saving && <LogOut aria-hidden="true" />}
        Confirm check-out
      </Button>
    </div>
  );
}

function Belongings({ items }: { items: string[] }) {
  return items.length > 0
    ? <Alert tone="info" title="Check their belongings">Belongings recorded at entry: <span className="caps">{items.join(", ")}</span>.</Alert>
    : null;
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
      <VisitSummary visit={visit} />
      <Belongings items={visit.belongings} />
      <ConfirmActions saving={saving} onConfirm={() => void confirm()} onCancel={onCancel} />
    </div>
  );
}

/** The visitor being checked out: photo, name, visit, host and time inside. */
function VisitSummary({ visit }: { visit: Visit }) {
  return (
    <div className="flex gap-4 rounded-xl border border-border bg-surface-subtle p-4">
      <div className="shrink-0 overflow-hidden rounded-xl">
        <VisitorPhoto photoId={visit.photo_id} name={visit.visitor.name} className="size-24" />
      </div>
      <dl className="min-w-0 space-y-1 text-sm">
        <div><dt className="sr-only">Visitor</dt><dd className="caps text-heading break-words text-ink" data-testid="scanned-visitor">{visit.visitor.name}</dd></div>
        <div><dt className="sr-only">Visit</dt><dd className="font-mono text-ink-muted">{visit.visit_number}</dd></div>
        <div><dt className="inline text-ink-muted">Visiting: </dt><dd className="caps inline text-ink">{visit.host.name}{visit.department.name ? ` (${visit.department.name})` : ""}</dd></div>
        <div>
          <dt className="inline text-ink-muted">Inside since: </dt>
          <dd className="inline text-ink tabular-nums">{formatTime(visit.check_in_at)} · <span className="caps">{visit.gate.name}</span> · {formatDuration(visit.check_in_at, visit.check_out_at)}</dd>
        </div>
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
          <div className="flex justify-end"><Button size="lg" onClick={onCancel} autoFocus>Close</Button></div>
        </>
      ) : (
        <>
          <p className="text-sm text-ink">Check that the person in front of you matches the photo, then confirm.</p>
          <Belongings items={visit.belongings} />
          <ConfirmActions saving={saving} onConfirm={() => void confirm()} onCancel={onCancel} />
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
        <BadgePreview issued={issued} visitId={visit.id} photoId={visit.photo_id} />
        <div className="flex justify-end"><Button variant="secondary" size="lg" onClick={onClose}>Close</Button></div>
      </div>
    );
  }
  return (
    <div className="space-y-4">
      {error && <Alert tone="danger">{error}</Alert>}
      <VisitSummary visit={visit} />
      <Alert tone="warn">Printing a new badge cancels the old one: its QR code will be refused at check-out.</Alert>
      <div className="flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
        <Button variant="secondary" size="lg" onClick={onClose} disabled={saving}>Cancel</Button>
        <Button size="lg" onClick={() => void reissue()} loading={saving}>
          {!saving && <Printer aria-hidden="true" />}
          Issue new badge
        </Button>
      </div>
    </div>
  );
}
