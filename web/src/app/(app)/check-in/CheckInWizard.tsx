"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { SelectField } from "@/components/ui/SelectField";
import { TextField } from "@/components/ui/TextField";
import { IdentityInput } from "@/components/visits/IdentityInput";
import { ApiError, errorMessage, fieldErrors } from "@/lib/api/client";
import { type Department, listDepartments } from "@/lib/api/directory";
import {
  createVisitor,
  getVisitor,
  IDENTITY_LABELS,
  type IdentityType,
  lookupVisitor,
  type Visitor,
  type VisitorWithStatus,
} from "@/lib/api/visitors";
import { checkIn, checkOut, reasonLabel, type Visit, VISIT_REASONS, type VisitReason } from "@/lib/api/visits";
import { formatDateTime, formatTime, parseList } from "@/lib/format";

import { type DraftErrors, EMPTY_DRAFT, effectiveDepartmentId, toCheckIn, validateDraft, type VisitDraft } from "./draft";
import { HostPicker } from "./HostPicker";

type Step =
  | { kind: "identify" }
  | { kind: "register" }
  | { kind: "blocked"; name: string; reason: string }
  | { kind: "inside"; visitor: Visitor }
  | { kind: "details"; visitor: Visitor }
  | { kind: "review"; visitor: Visitor }
  | { kind: "done"; visit: Visit };

const STEP_TITLES = ["Identify visitor", "Visit details", "Confirm"];

function stepIndex(step: Step): number {
  if (step.kind === "details") return 1;
  if (step.kind === "review" || step.kind === "done") return 2;
  return 0;
}

/**
 * Check-in: identify by ID → register if new → screening / already-inside
 * checks → visit details → review → confirm. The API re-checks everything
 * (watchlist, one active visit, host/department) at confirmation.
 */
export function CheckInWizard() {
  const [step, setStep] = useState<Step>({ kind: "identify" });
  const [idType, setIdType] = useState<IdentityType>("CNIC");
  const [idNumber, setIdNumber] = useState("");
  const [draft, setDraft] = useState<VisitDraft>(EMPTY_DRAFT);

  function restart() {
    setStep({ kind: "identify" });
    setIdNumber("");
    setDraft(EMPTY_DRAFT);
  }

  function route(found: VisitorWithStatus) {
    const { visitor, screening } = found;
    if (screening.status === "BLOCKED") {
      setStep({ kind: "blocked", name: visitor.full_name, reason: screening.reason ?? "" });
    } else if (visitor.active_visit) {
      setStep({ kind: "inside", visitor });
    } else {
      setStep({ kind: "details", visitor });
    }
  }

  return (
    <div className="space-y-4">
      <ol className="flex gap-2 text-sm" aria-label="Check-in steps">
        {STEP_TITLES.map((title, i) => (
          <li key={title} aria-current={i === stepIndex(step) ? "step" : undefined}
              className={`flex-1 rounded-lg px-3 py-2 font-medium ${i === stepIndex(step)
                ? "bg-brand-600 text-white" : i < stepIndex(step) ? "bg-brand-50 text-brand-700" : "bg-canvas text-ink-muted"}`}>
            {i + 1}. {title}
          </li>
        ))}
      </ol>

      {step.kind === "identify" && (
        <IdentifyStep idType={idType} idNumber={idNumber} onType={setIdType} onNumber={setIdNumber}
                      onFound={route} onNotRegistered={() => setStep({ kind: "register" })} />
      )}
      {step.kind === "register" && (
        <RegisterStep idType={idType} idNumber={idNumber} onBack={() => setStep({ kind: "identify" })}
                      onRegistered={route} />
      )}
      {step.kind === "blocked" && <BlockedStep name={step.name} reason={step.reason} onDone={restart} />}
      {step.kind === "inside" && (
        <InsideStep visitor={step.visitor} onCancel={restart}
                    onCheckedOut={() => setStep({ kind: "details", visitor: { ...step.visitor, active_visit: null } })} />
      )}
      {step.kind === "details" && (
        <DetailsStep visitor={step.visitor} draft={draft} onChange={setDraft} onCancel={restart}
                     onNext={() => setStep({ kind: "review", visitor: step.visitor })} />
      )}
      {step.kind === "review" && (
        <ReviewStep visitor={step.visitor} draft={draft} onBack={() => setStep({ kind: "details", visitor: step.visitor })}
                    onDenied={(reason) => setStep({ kind: "blocked", name: step.visitor.full_name, reason })}
                    onDone={(visit) => setStep({ kind: "done", visit })} />
      )}
      {step.kind === "done" && <DoneStep visit={step.visit} onNext={restart} />}
    </div>
  );
}

// ---------------------------------------------------------------- step 1: identify
function IdentifyStep({ idType, idNumber, onType, onNumber, onFound, onNotRegistered }: {
  idType: IdentityType;
  idNumber: string;
  onType: (t: IdentityType) => void;
  onNumber: (n: string) => void;
  onFound: (found: VisitorWithStatus) => void;
  onNotRegistered: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [fieldError, setFieldError] = useState<string | undefined>();
  const [searching, setSearching] = useState(false);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setFieldError(undefined);
    if (!idNumber.trim()) return setFieldError("Enter the visitor's ID number.");
    setSearching(true);
    try {
      onFound(await lookupVisitor(idType, idNumber));
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) onNotRegistered();
      else if (e instanceof ApiError && e.status === 422) setFieldError(e.details[0]?.message ?? e.message);
      else setError(errorMessage(e));
    } finally {
      setSearching(false);
    }
  }

  return (
    <Card title="Who is visiting?" description="Enter the ID number from the visitor's identity document.">
      <form onSubmit={onSubmit} noValidate className="space-y-4">
        {error && <Alert tone="danger">{error}</Alert>}
        <IdentityInput type={idType} number={idNumber} onType={onType} onNumber={onNumber} error={fieldError} autoFocus />
        <div className="flex justify-end">
          <Button type="submit" loading={searching}>Find visitor</Button>
        </div>
      </form>
    </Card>
  );
}

// ---------------------------------------------------------------- new visitor
function RegisterStep({ idType, idNumber, onBack, onRegistered }: {
  idType: IdentityType;
  idNumber: string;
  onBack: () => void;
  onRegistered: (found: VisitorWithStatus) => void;
}) {
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setErrors({});
    if (!name.trim()) return setErrors({ full_name: "Enter the visitor's full name." });
    setSaving(true);
    try {
      const identity = { type: idType, number: idNumber };
      let visitorId: string;
      try {
        visitorId = (await createVisitor({ full_name: name, identity, phone: phone.trim() || null })).id;
      } catch (e) {
        // Registered at another gate a moment ago: continue with that record.
        if (!(e instanceof ApiError && e.code === "visitor_exists")) throw e;
        visitorId = (await lookupVisitor(idType, idNumber)).visitor.id;
      }
      onRegistered(await getVisitor(visitorId));
    } catch (e) {
      const byField = fieldErrors(e);
      if (Object.keys(byField).length) {
        setErrors(byField);
      } else {
        setError(errorMessage(e));
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card title="New visitor" description="This ID number is not registered yet. Add the visitor's details.">
      <form onSubmit={onSubmit} noValidate className="space-y-4">
        {error && <Alert tone="danger">{error}</Alert>}
        <p className="text-sm">
          <span className="text-ink-muted">{IDENTITY_LABELS[idType]}: </span>
          <span className="font-semibold text-ink">{idNumber}</span>
        </p>
        {(errors.identity || errors._form) && <Alert tone="danger">{errors.identity || errors._form}</Alert>}
        <TextField label="Full name" value={name} onChange={(e) => setName(e.target.value)} error={errors.full_name}
                   autoComplete="off" autoFocus />
        <TextField label="Phone (optional)" value={phone} onChange={(e) => setPhone(e.target.value)} error={errors.phone}
                   inputMode="tel" autoComplete="off" />
        <div className="flex justify-between gap-2">
          <Button type="button" variant="secondary" onClick={onBack}>Back</Button>
          <Button type="submit" loading={saving}>Register and continue</Button>
        </div>
      </form>
    </Card>
  );
}

// ---------------------------------------------------------------- stops
function BlockedStep({ name, reason, onDone }: { name: string; reason: string; onDone: () => void }) {
  return (
    <Card title="Entry not permitted">
      <div className="space-y-4" data-testid="entry-denied">
        <Alert tone="danger">
          <p className="font-semibold">{name} is on the watchlist and must not be admitted.</p>
          {reason && <p className="mt-1">Reason: {reason}</p>}
        </Alert>
        <p className="text-sm text-ink-muted">Follow the security procedure and inform your supervisor. This attempt has been logged.</p>
        <div className="flex justify-end"><Button onClick={onDone}>Done</Button></div>
      </div>
    </Card>
  );
}

function InsideStep({ visitor, onCancel, onCheckedOut }: {
  visitor: Visitor;
  onCancel: () => void;
  onCheckedOut: () => void;
}) {
  const active = visitor.active_visit!;
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function checkOutNow() {
    setError(null);
    setSaving(true);
    try {
      await checkOut(active.id);
      onCheckedOut();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card title="Already inside">
      <div className="space-y-4">
        {error && <Alert tone="danger">{error}</Alert>}
        <Alert tone="warn">
          {visitor.full_name} is already checked in (visit <strong>{active.visit_number}</strong>, since{" "}
          {formatTime(active.check_in_at)}{active.gate_name ? ` at ${active.gate_name}` : ""}).
        </Alert>
        <p className="text-sm text-ink-muted">
          If they left without checking out, check that visit out first, then record the new visit.
        </p>
        <div className="flex justify-between gap-2">
          <Button variant="secondary" onClick={onCancel}>Cancel</Button>
          <Button onClick={() => void checkOutNow()} loading={saving}>Check out previous visit and continue</Button>
        </div>
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------- step 2: visit details
function VisitorSummary({ visitor }: { visitor: Visitor }) {
  return (
    <div className="rounded-lg bg-canvas px-4 py-3 text-sm">
      <p className="text-base font-semibold text-ink" data-testid="visitor-name">{visitor.full_name}</p>
      <p className="text-ink-muted">
        {visitor.identity && `${IDENTITY_LABELS[visitor.identity.type]} ${visitor.identity.number}`}
        {visitor.phone && ` · ${visitor.phone}`}
      </p>
    </div>
  );
}

export function DetailsStep({ visitor, draft, onChange, onCancel, onNext }: {
  visitor: Visitor;
  draft: VisitDraft;
  onChange: (draft: VisitDraft) => void;
  onCancel: () => void;
  onNext: () => void;
}) {
  const [departments, setDepartments] = useState<Department[]>([]);
  const [errors, setErrors] = useState<DraftErrors>({});
  const set = (changes: Partial<VisitDraft>) => onChange({ ...draft, ...changes });

  useEffect(() => {
    const controller = new AbortController();
    listDepartments(false, controller.signal).then(setDepartments).catch(() => {});
    return () => controller.abort();
  }, []);

  function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    const problems = validateDraft(draft);
    setErrors(problems);
    if (Object.keys(problems).length === 0) onNext();
  }

  const hostDepartment = !draft.unlistedHost ? draft.host?.department_name : null;
  return (
    <Card title="Visit details">
      <form onSubmit={onSubmit} noValidate className="space-y-4">
        <VisitorSummary visitor={visitor} />
        {draft.unlistedHost ? (
          <TextField label="Name of the person being visited" value={draft.unlistedHostName} autoComplete="off"
                     onChange={(e) => set({ unlistedHostName: e.target.value })} error={errors.host}
                     hint="The visit is flagged so an administrator can add this person to the directory." />
        ) : (
          <HostPicker value={draft.host} onChange={(host) => set({ host, departmentId: "" })} error={errors.host} />
        )}
        <label className="flex items-center gap-2 text-sm text-ink">
          <input type="checkbox" className="size-4" checked={draft.unlistedHost}
                 onChange={(e) => set({ unlistedHost: e.target.checked, host: null, departmentId: "" })} />
          The host is not in the list
        </label>
        <SelectField label="Department" value={draft.departmentId} error={errors.department}
                     onChange={(e) => set({ departmentId: e.target.value })}>
          <option value="">{hostDepartment ? `${hostDepartment} (host's department)` : "Choose a department"}</option>
          {departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
        </SelectField>
        <SelectField label="Reason for visit" value={draft.reason} error={errors.reason}
                     onChange={(e) => set({ reason: e.target.value as VisitReason | "" })}>
          <option value="">Choose a reason</option>
          {VISIT_REASONS.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
        </SelectField>
        {draft.reason === "OTHER" && (
          <TextField label="Describe the reason" value={draft.reasonNote} maxLength={200} error={errors.reasonNote}
                     onChange={(e) => set({ reasonNote: e.target.value })} />
        )}
        <div className="grid gap-4 sm:grid-cols-2">
          <TextField label="Vehicle registration (optional)" value={draft.vehicle} autoComplete="off"
                     onChange={(e) => set({ vehicle: e.target.value })} placeholder="LEA-1234" />
          <TextField label="Belongings (optional)" value={draft.belongings} error={errors.belongings}
                     onChange={(e) => set({ belongings: e.target.value })} hint="Separate items with commas." />
        </div>
        <div className="flex justify-between gap-2">
          <Button type="button" variant="secondary" onClick={onCancel}>Cancel</Button>
          <Button type="submit">Review</Button>
        </div>
      </form>
    </Card>
  );
}

// ---------------------------------------------------------------- step 3: review and confirm
function ReviewStep({ visitor, draft, onBack, onDenied, onDone }: {
  visitor: Visitor;
  draft: VisitDraft;
  onBack: () => void;
  onDenied: (reason: string) => void;
  onDone: (visit: Visit) => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [problems, setProblems] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [departments, setDepartments] = useState<Department[]>([]);

  useEffect(() => {
    const controller = new AbortController();
    listDepartments(false, controller.signal).then(setDepartments).catch(() => {});
    return () => controller.abort();
  }, []);

  async function confirm() {
    setError(null);
    setProblems([]);
    setSaving(true);
    try {
      onDone(await checkIn(toCheckIn(visitor.id, draft)));
    } catch (e) {
      if (e instanceof ApiError && e.code === "entry_denied") return onDenied(e.message);
      setError(errorMessage(e));
      if (e instanceof ApiError) setProblems(e.details.map((d) => d.message));
    } finally {
      setSaving(false);
    }
  }

  const departmentId = effectiveDepartmentId(draft);
  const departmentName = departments.find((d) => d.id === departmentId)?.name
    ?? (draft.host?.department_id === departmentId ? draft.host?.department_name : null) ?? "—";
  const belongings = parseList(draft.belongings);
  const rows: [string, React.ReactNode][] = [
    ["Visitor", visitor.full_name],
    ["ID", visitor.identity ? `${IDENTITY_LABELS[visitor.identity.type]} ${visitor.identity.number}` : "—"],
    ["Host", draft.unlistedHost ? `${draft.unlistedHostName.trim()} (not in directory)` : draft.host?.name],
    ["Department", departmentName],
    ["Reason", draft.reason ? `${reasonLabel(draft.reason)}${draft.reasonNote.trim() ? ` — ${draft.reasonNote.trim()}` : ""}` : "—"],
    ["Vehicle", draft.vehicle.trim().toUpperCase() || "—"],
    ["Belongings", belongings.length ? belongings.join(", ") : "—"],
  ];

  return (
    <Card title="Confirm check-in" description="Check the details with the visitor before confirming.">
      <div className="space-y-4">
        {error && (
          <Alert tone="danger">
            <p>{error}</p>
            {problems.length > 0 && <ul className="mt-1 list-disc pl-5">{problems.map((p) => <li key={p}>{p}</li>)}</ul>}
          </Alert>
        )}
        <dl className="divide-y divide-border rounded-lg border border-border text-sm">
          {rows.map(([label, value]) => (
            <div key={label} className="grid grid-cols-[9rem_1fr] gap-3 px-4 py-2">
              <dt className="text-ink-muted">{label}</dt>
              <dd className="font-medium text-ink">{value}</dd>
            </div>
          ))}
        </dl>
        <div className="flex justify-between gap-2">
          <Button variant="secondary" onClick={onBack} disabled={saving}>Back</Button>
          <Button onClick={() => void confirm()} loading={saving}>Confirm check-in</Button>
        </div>
      </div>
    </Card>
  );
}

function DoneStep({ visit, onNext }: { visit: Visit; onNext: () => void }) {
  return (
    <Card title="Checked in">
      <div className="space-y-4 text-center" data-testid="check-in-done">
        <Alert tone="ok">{visit.visitor.name} has been checked in.</Alert>
        <div>
          <p className="text-sm text-ink-muted">Visit number</p>
          <p className="font-mono text-3xl font-bold tracking-wide text-ink" data-testid="visit-number">{visit.visit_number}</p>
        </div>
        <p className="text-sm text-ink-muted">
          Visiting {visit.host.name}{visit.department.name ? ` (${visit.department.name})` : ""} · {visit.gate.name} ·{" "}
          {formatDateTime(visit.check_in_at)}
        </p>
        {visit.host_unlisted && (
          <Alert tone="warn">The host is not in the directory; this visit is flagged for review.</Alert>
        )}
        <div className="flex justify-center gap-2">
          <Link href="/check-out" className="inline-flex min-h-10 items-center rounded-lg border border-border px-4 text-sm font-semibold text-ink hover:bg-canvas">
            Visitors inside
          </Link>
          <Button onClick={onNext} autoFocus>Check in next visitor</Button>
        </div>
      </div>
    </Card>
  );
}
