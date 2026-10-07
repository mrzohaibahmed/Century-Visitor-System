"use client";

import { Plus, Trash2 } from "lucide-react";
import { useEffect, useId, useState } from "react";

import { Button } from "@/components/ui/Button";
import { controlClasses, describedBy, FieldMessage } from "@/components/ui/Field";
import { Modal } from "@/components/ui/Modal";
import { TextField } from "@/components/ui/TextField";

import {
  type BelongingItem,
  emptyBelongingItem,
  filledBelongings,
  MAX_BELONGINGS,
  type PersonalMaterial,
} from "./draft";

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

export function PersonalMaterialForm({ open, value, vehicle, defaultContact, error, onClose, onSave }: {
  open: boolean;
  value: PersonalMaterial;
  vehicle: string;
  /** Prefill Company Cont. Name when the slip has none yet (usually the host). */
  defaultContact?: string;
  error?: string;
  onClose: () => void;
  onSave: (next: { personalMaterial: PersonalMaterial; vehicle: string }) => void;
}) {
  const [draft, setDraft] = useState<PersonalMaterial>(value);
  const [veh, setVeh] = useState(vehicle);
  const [formError, setFormError] = useState<string | undefined>();

  // Reset local state whenever the dialog opens so Cancel discards edits.
  useEffect(() => {
    if (!open) return;
    setDraft({
      ...value,
      contactName: value.contactName || defaultContact || "",
      items: value.items.length ? value.items.map((r) => ({ ...r })) : [emptyBelongingItem()],
    });
    setVeh(vehicle);
    setFormError(undefined);
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps -- snapshot props only when opening

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
    const items = filled.length ? filled : [emptyBelongingItem()];
    onSave({ personalMaterial: { ...draft, items }, vehicle: veh });
  }

  const count = filledBelongings(draft).length;

  return (
    <Modal
      open={open}
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
            value="—"
            disabled
            hint="Assigned after check-in."
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
                      onChange={(description) => setItem(index, { description })}
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

        <div className="flex justify-end gap-2 border-t border-border pt-5">
          <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit">Save belongings</Button>
        </div>
      </form>
    </Modal>
  );
}
