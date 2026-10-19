"use client";

import { Plus, Printer, Trash2 } from "lucide-react";
import Image from "next/image";
import { useEffect, useId, useState } from "react";
import { createPortal } from "react-dom";

import crest from "@/assets/century-crest.png";
import { useQrDataUrl } from "@/components/badge/VisitorBadge";
import { Button } from "@/components/ui/Button";
import { controlClasses, describedBy, FieldMessage } from "@/components/ui/Field";
import { Modal } from "@/components/ui/Modal";
import { TextField } from "@/components/ui/TextField";
import { errorMessage } from "@/lib/api/client";
import { printablePass, verifyPassForPrint } from "@/lib/api/passes";
import { printOnly } from "@/lib/print";

import {
  type BelongingItem,
  emptyBelongingItem,
  filledBelongings,
  MAX_BELONGINGS,
  type PersonalMaterial,
} from "@/lib/belongings";

/** Compact cell input for the items table (no outer label; header supplies the name). */
function CellInput({ label, value, onChange, caps = false, className = "", ...props }: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  caps?: boolean;
  className?: string;
} & Omit<React.InputHTMLAttributes<HTMLInputElement>, "value" | "onChange" | "size" | "className">) {
  const id = useId();
  return (
    <input
      id={id}
      aria-label={label}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={`${controlClasses({ size: "md" })} min-h-11 px-2.5 text-base${caps ? " caps" : ""} ${className}`}
      {...props}
    />
  );
}

function TextAreaField({ label, value, onChange, hint }: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  hint?: string;
}) {
  const id = useId();
  return (
    <div>
      <label htmlFor={id} className="mb-1.5 block text-sm font-medium text-ink">{label}</label>
      <textarea
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={2}
        aria-describedby={describedBy(id, hint)}
        className={`${controlClasses({ size: "md" })} min-h-[4.5rem] resize-y py-2.5`}
      />
      <FieldMessage id={id} hint={hint} />
    </div>
  );
}

export function PersonalMaterialForm({
  open, value, vehicle, defaultContact, visitorName, visitId, visitNumber, passQrText, error, onClose, onSave,
}: {
  open: boolean;
  value: PersonalMaterial;
  vehicle: string;
  /** Prefill Company Cont. Name when the slip has none yet (usually the host). */
  defaultContact?: string;
  visitorName?: string;
  visitId?: string;
  visitNumber?: string;
  passQrText?: string;
  error?: string;
  onClose: () => void;
  onSave: (next: { personalMaterial: PersonalMaterial; vehicle: string }) => void;
}) {
  if (!open) return null;
  return (
    <OpenPersonalMaterialForm
      value={value}
      vehicle={vehicle}
      defaultContact={defaultContact}
      visitorName={visitorName}
      visitId={visitId}
      visitNumber={visitNumber}
      passQrText={passQrText}
      error={error}
      onClose={onClose}
      onSave={onSave}
    />
  );
}

function OpenPersonalMaterialForm({
  value, vehicle, defaultContact, visitorName, visitId, visitNumber, passQrText, error, onClose, onSave,
}: {
  value: PersonalMaterial;
  vehicle: string;
  defaultContact?: string;
  visitorName?: string;
  visitId?: string;
  visitNumber?: string;
  passQrText?: string;
  error?: string;
  onClose: () => void;
  onSave: (next: { personalMaterial: PersonalMaterial; vehicle: string }) => void;
}) {
  const [draft, setDraft] = useState<PersonalMaterial>(() => ({
    ...value,
    contactName: value.contactName || defaultContact || "",
    items: value.items.length
      ? value.items.map((row) => ({ ...row, description: row.description.toUpperCase() }))
      : [emptyBelongingItem()],
  }));
  const [veh, setVeh] = useState(vehicle);
  const [formError, setFormError] = useState<string | undefined>();
  const [printRoot, setPrintRoot] = useState<HTMLElement | null>(null);
  const [fetchedQrText, setFetchedQrText] = useState<string | null>(null);
  const [invalidQrText, setInvalidQrText] = useState<string | null>(null);
  const [qrError, setQrError] = useState<string | null>(null);
  const [scannedQrText, setScannedQrText] = useState("");
  const [checkingQr, setCheckingQr] = useState(false);
  const candidateQrText = passQrText || fetchedQrText;
  const qrText = candidateQrText === invalidQrText ? null : candidateQrText;
  const qr = useQrDataUrl(qrText);

  useEffect(() => {
    if (!visitId || passQrText) return;
    let current = true;
    printablePass(visitId)
      .then((pass) => { if (current) { setFetchedQrText(pass.qr_text); setInvalidQrText(null); setQrError(null); } })
      .catch((cause) => { if (current) setQrError(errorMessage(cause)); });
    return () => { current = false; };
  }, [visitId, passQrText]);

  async function confirmScannedBadge() {
    if (!visitId || !scannedQrText.trim()) return;
    setCheckingQr(true);
    setQrError(null);
    try {
      const pass = await verifyPassForPrint(visitId, scannedQrText.trim());
      setFetchedQrText(pass.qr_text);
      setInvalidQrText(null);
      setScannedQrText("");
    } catch (cause) {
      setQrError(errorMessage(cause));
    } finally {
      setCheckingQr(false);
    }
  }

  async function print() {
    if (!visitId || !visitNumber || !qr || !qrText) return;
    setQrError(null);
    try {
      // The badge could have been reissued after the form opened. Check again
      // before putting a credential on paper.
      await verifyPassForPrint(visitId, qrText);
      printOnly("belongings");
    } catch (cause) {
      setInvalidQrText(qrText);
      setQrError(errorMessage(cause));
    }
  }

  useEffect(() => {
    const root = document.createElement("div");
    root.className = "belongings-print-root";
    root.setAttribute("aria-hidden", "true");
    document.body.appendChild(root);
    // The print-only copy is attached to <body> after this client component mounts.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setPrintRoot(root);
    return () => root.remove();
  }, []);

  function setItem(index: number, patch: Partial<BelongingItem>) {
    setDraft((d) => ({
      ...d,
      items: d.items.map((row, i) => (i === index ? { ...row, ...patch } : row)),
    }));
  }

  function addRow() {
    setDraft((d) => {
      if (d.items.length >= MAX_BELONGINGS) return d;
      return { ...d, items: [...d.items, emptyBelongingItem()] };
    });
  }

  function removeRow(index: number) {
    setDraft((d) => {
      const items = d.items.filter((_, i) => i !== index);
      return { ...d, items: items.length ? items : [emptyBelongingItem()] };
    });
  }

  function submit(event: React.FormEvent) {
    event.preventDefault();
    const filled = filledBelongings(draft);
    if (filled.length > MAX_BELONGINGS) {
      setFormError(`At most ${MAX_BELONGINGS} items.`);
      return;
    }
    // Drop trailing blank rows; keep at least one empty row when nothing was entered.
    const items = filled.length
      ? filled.map((row) => ({ ...row, description: row.description.trim().toUpperCase() }))
      : [emptyBelongingItem()];
    onSave({ personalMaterial: { ...draft, items }, vehicle: veh });
  }

  const count = filledBelongings(draft).length;

  return (
    <Modal
      open
      title="Personal Material Returnable"
      description="Record items the visitor brings in. They must be checked again at exit."
      onClose={onClose}
      size="xl"
    >
      <form onSubmit={submit} noValidate className="space-y-5">
        <p className="text-center text-xs font-semibold tracking-wide text-ink-muted uppercase">
          Century Paper &amp; Board Mills Ltd.
        </p>

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <TextField
            label="S. No."
            value={visitNumber || "Assigned at check-in"}
            disabled
            hint="Same visit number as the visitor badge."
          />
          <TextField
            label="Veh. #"
            value={veh}
            onChange={(e) => setVeh(e.target.value)}
            autoComplete="off"
            caps
            placeholder="LEA-1234"
          />
          <TextField
            label="Company Cont. Name"
            value={draft.contactName}
            onChange={(e) => setDraft({ ...draft, contactName: e.target.value })}
            autoComplete="off"
            caps
          />
          <TextField
            label="Date"
            type="date"
            value={draft.date}
            onChange={(e) => setDraft({ ...draft, date: e.target.value })}
          />
        </div>

        {visitId && (
          <div className="flex flex-wrap items-center gap-4 rounded-xl border border-border bg-surface-subtle p-3">
            {qr ? <Image src={qr} alt="Visitor badge QR code" width={84} height={84} unoptimized /> : null}
            <div className="min-w-0 flex-1 space-y-2">
              <p className="text-sm font-medium text-ink">
                {qr ? "Matching visitor badge QR ready" : qrError || "Loading the visitor badge QR…"}
              </p>
              {!qr && qrError && (
                <div className="flex flex-wrap items-end gap-2">
                  <TextField label="Scan current visitor badge" value={scannedQrText}
                             onChange={(e) => setScannedQrText(e.target.value)} autoComplete="off"
                             onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); void confirmScannedBadge(); } }} />
                  <Button type="button" variant="secondary" loading={checkingQr}
                          disabled={!scannedQrText.trim()} onClick={() => void confirmScannedBadge()}>
                    Use scanned badge
                  </Button>
                </div>
              )}
            </div>
          </div>
        )}

        <div className="overflow-x-auto rounded-xl border border-border">
          <table className="w-full min-w-[28rem] border-collapse text-left text-sm">
            <thead>
              <tr className="border-b border-border bg-surface-subtle text-ink-muted">
                <th scope="col" className="w-12 px-2 py-2.5 text-center font-semibold">SR #</th>
                <th scope="col" className="px-2 py-2.5 font-semibold">Description</th>
                <th scope="col" className="w-20 px-2 py-2.5 text-center font-semibold">Qty in</th>
                <th scope="col" className="w-20 px-2 py-2.5 text-center font-semibold">Qty out</th>
                <th scope="col" className="w-12 px-1 py-2.5"><span className="sr-only">Remove</span></th>
              </tr>
            </thead>
            <tbody>
              {draft.items.map((row, index) => (
                <tr key={index} className="border-b border-border last:border-b-0">
                  <td className="px-2 py-1.5 text-center font-mono text-ink-muted">{index + 1}</td>
                  <td className="px-2 py-1.5">
                    <CellInput
                      label={`Description ${index + 1}`}
                      value={row.description}
                      onChange={(description) => setItem(index, { description: description.toUpperCase() })}
                      caps
                      maxLength={40}
                    />
                  </td>
                  <td className="px-2 py-1.5">
                    <CellInput
                      label={`Quantity in ${index + 1}`}
                      value={row.qtyIn}
                      onChange={(qtyIn) => setItem(index, { qtyIn })}
                      inputMode="numeric"
                      className="text-center font-mono"
                      maxLength={4}
                    />
                  </td>
                  <td className="px-2 py-1.5">
                    <CellInput
                      label={`Quantity out ${index + 1}`}
                      value={row.qtyOut}
                      onChange={(qtyOut) => setItem(index, { qtyOut })}
                      inputMode="numeric"
                      className="text-center font-mono"
                      maxLength={4}
                    />
                  </td>
                  <td className="px-1 py-1.5 text-center">
                    <button
                      type="button"
                      onClick={() => removeRow(index)}
                      aria-label={`Remove row ${index + 1}`}
                      className="inline-flex size-10 items-center justify-center rounded-lg text-ink-muted
                        transition-colors hover:bg-canvas hover:text-danger"
                    >
                      <Trash2 aria-hidden="true" className="size-4" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3">
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={addRow}
            disabled={draft.items.length >= MAX_BELONGINGS}
          >
            <Plus aria-hidden="true" />
            Add item
          </Button>
          <p className="text-sm text-ink-muted">{count} of {MAX_BELONGINGS} items</p>
        </div>

        {(formError || error) && (
          <p role="alert" className="text-sm text-danger">{formError || error}</p>
        )}

        <TextAreaField
          label="Remarks"
          value={draft.remarks}
          onChange={(remarks) => setDraft({ ...draft, remarks })}
        />

        <div className="grid gap-4 sm:grid-cols-3">
          <TextField
            label="Authorised by"
            value={draft.authorisedBy}
            onChange={(e) => setDraft({ ...draft, authorisedBy: e.target.value })}
            autoComplete="off"
            caps
          />
          <TextField
            label="Issued by"
            value={draft.issuedBy}
            onChange={(e) => setDraft({ ...draft, issuedBy: e.target.value })}
            autoComplete="off"
            caps
          />
          <TextField
            label="Gate officer"
            value={draft.gateOfficer}
            onChange={(e) => setDraft({ ...draft, gateOfficer: e.target.value })}
            autoComplete="off"
            caps
          />
        </div>

        <div className="flex flex-col-reverse gap-2 border-t border-border pt-5 sm:flex-row sm:justify-between">
          <Button type="button" variant="secondary" disabled={!visitId || !visitNumber || !qr}
                  onClick={() => void print()}>
            <Printer aria-hidden="true" />
            Print belongings list
          </Button>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
            <Button type="submit">Save belongings</Button>
          </div>
        </div>
      </form>
      {printRoot && createPortal(
        <PersonalMaterialPrint
          value={draft}
          vehicle={veh}
          visitorName={visitorName}
          visitNumber={visitNumber}
          qr={qr}
        />,
        printRoot,
      )}
    </Modal>
  );
}

/** Print a saved form directly from the check-in completion screen. */
export function PersonalMaterialPrintButton({
  value, vehicle, visitorName, visitId, visitNumber, passQrText,
}: {
  value: PersonalMaterial;
  vehicle: string;
  visitorName: string;
  visitId: string;
  visitNumber: string;
  passQrText: string;
}) {
  const qr = useQrDataUrl(passQrText);
  const [printRoot, setPrintRoot] = useState<HTMLElement | null>(null);
  const [printError, setPrintError] = useState<string | null>(null);
  const [printing, setPrinting] = useState(false);

  useEffect(() => {
    const root = document.createElement("div");
    root.className = "belongings-print-root belongings-print-root--completion";
    root.setAttribute("aria-hidden", "true");
    document.body.appendChild(root);
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setPrintRoot(root);
    return () => root.remove();
  }, []);

  async function print() {
    if (!qr || !printRoot || printing) return;
    setPrintError(null);
    setPrinting(true);
    try {
      await verifyPassForPrint(visitId, passQrText);
      printOnly("belongings", "completion");
    } catch (cause) {
      setPrintError(errorMessage(cause));
    } finally {
      setPrinting(false);
    }
  }

  return (
    <div className="space-y-2">
      <Button type="button" variant="secondary" size="lg" className="w-full"
              disabled={!qr || !printRoot} loading={printing} onClick={() => void print()}>
        <Printer aria-hidden="true" />
        Print personal belongings form
      </Button>
      {printError && <p role="alert" className="text-sm text-danger">{printError}</p>}
      {printRoot && createPortal(
        <PersonalMaterialPrint value={value} vehicle={vehicle} visitorName={visitorName}
                               visitNumber={visitNumber} qr={qr} />,
        printRoot,
      )}
    </div>
  );
}

function PersonalMaterialPrint({ value, vehicle, visitorName, visitNumber, qr }: {
  value: PersonalMaterial;
  vehicle: string;
  visitorName?: string;
  visitNumber?: string;
  qr: string | null;
}) {
  const rows = filledBelongings(value);
  const printRows = Array.from({ length: MAX_BELONGINGS }, (_, index) => rows[index] ?? null);
  return (
    <article className="belongings-print-sheet">
      <header className="belongings-print-header">
        <Image
          src={crest}
          alt="Century Paper and Board Mills logo"
          width={512}
          height={364}
          className="belongings-print-logo"
          loading="eager"
          unoptimized
        />
        <div className="belongings-print-brand">
          <p className="belongings-print-company">Century Paper &amp; Board Mills Limited</p>
          <p className="belongings-print-department">Security Department · Gate Control</p>
        </div>
        {qr && <div className="belongings-print-qr">
          <Image src={qr} alt="Visitor badge QR code" width={120} height={120} unoptimized />
          <span>Visitor badge QR</span>
        </div>}
      </header>
      <section className="belongings-print-title-band">
        <p className="belongings-print-title">Personal Material Returnable</p>
        <p>Visitor belongings register</p>
      </section>
      <dl className="belongings-print-facts">
        <div><dt>S. No. / Visit no.</dt><dd>{visitNumber || "—"}</dd></div>
        <div><dt>Date</dt><dd>{value.date || "—"}</dd></div>
        <div><dt>Vehicle registration</dt><dd>{vehicle.trim().toUpperCase() || "—"}</dd></div>
        <div className="belongings-print-fact-wide"><dt>Visitor name</dt><dd>{visitorName || "—"}</dd></div>
        <div className="belongings-print-fact-wide"><dt>Company contact</dt><dd>{value.contactName.trim() || "—"}</dd></div>
      </dl>
      <table className="belongings-print-table">
        <thead>
          <tr><th>Sr. no.</th><th>Item description</th><th>Qty. in</th><th>Qty. out</th></tr>
        </thead>
        <tbody>
          {printRows.map((row, index) => (
            <tr key={index}>
              <td>{index + 1}</td>
              <td>{row?.description.trim().toUpperCase() || ""}</td>
              <td>{row?.qtyIn || ""}</td>
              <td>{row?.qtyOut || ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <section className="belongings-print-remarks">
        <h2>Remarks</h2>
        <p>{value.remarks.trim() || "—"}</p>
      </section>
      <dl className="belongings-print-signatures">
        <div><dt>Authorised by</dt><dd>{value.authorisedBy.trim()}</dd></div>
        <div><dt>Issued by</dt><dd>{value.issuedBy.trim()}</dd></div>
        <div><dt>Gate officer</dt><dd>{value.gateOfficer.trim()}</dd></div>
      </dl>
      <footer className="belongings-print-footer">
        <p>All listed material must be verified at the gate before release.</p>
        <p>Century Gate Visitor Management System</p>
      </footer>
    </article>
  );
}
