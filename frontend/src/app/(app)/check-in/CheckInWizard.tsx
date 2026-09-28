"use client";

import {
  ArrowLeft, ArrowRight, Camera, Check, ClipboardCheck, ClipboardList, IdCard, Pencil, Printer, RotateCcw, Search, UserPlus, Users,
} from "lucide-react";
import { useCallback, useEffect, useId, useRef, useState } from "react";

import { BadgePreview } from "@/components/badge/VisitorBadge";
import { CameraCapture } from "@/components/camera/CameraCapture";
import { Alert } from "@/components/ui/Alert";
import { Avatar } from "@/components/ui/Avatar";
import { Button, ButtonLink } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Checkbox } from "@/components/ui/Checkbox";
import { DescriptionList } from "@/components/ui/DescriptionList";
import { SelectField } from "@/components/ui/SelectField";
import { Skeleton } from "@/components/ui/Skeleton";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { Stepper } from "@/components/ui/Stepper";
import { TextField } from "@/components/ui/TextField";
import { IdentityInput } from "@/components/visits/IdentityInput";
import { VisitorPhoto } from "@/components/visits/VisitorPhoto";
import { ApiError, errorMessage, fieldErrors } from "@/lib/api/client";
import { type Department, listDepartments } from "@/lib/api/directory";
import { type IssuedPass, issuePass } from "@/lib/api/passes";
import { uploadVisitorPhoto } from "@/lib/api/photos";
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
  | { kind: "photo"; visitor: Visitor }
  | { kind: "review"; visitor: Visitor; photoId: string | null }
  | { kind: "done"; visit: Visit };

const STEP_TITLES = ["Identify visitor", "Visit details", "Photo", "Confirm"];

function stepIndex(step: Step): number {
  if (step.kind === "details") return 1;
  if (step.kind === "photo") return 2;
  if (step.kind === "review") return 3;
  if (step.kind === "done") return STEP_TITLES.length;                  // every step complete
  return 0;
}

/**
 * Check-in: identify by ID → register if new → screening / already-inside
 * checks → visit details → photo → review → confirm → pass and badge. The API
 * re-checks everything (watchlist, one active visit, host/department, photo)
 * at confirmation.
 */
export function CheckInWizard() {
  const [step, setStep] = useState<Step>({ kind: "identify" });
  const [idType, setIdType] = useState<IdentityType>("CNIC");
  const [idNumber, setIdNumber] = useState("");
  const [draft, setDraft] = useState<VisitDraft>(EMPTY_DRAFT);
  /** The photo uploaded during this check-in (so the photo step does not call it one from an earlier visit). */
  const [capturedPhotoId, setCapturedPhotoId] = useState<string | null>(null);

  function restart() {
    setStep({ kind: "identify" });
    setIdNumber("");
    setDraft(EMPTY_DRAFT);
    setCapturedPhotoId(null);
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
    <div className="space-y-6">
      <Stepper steps={STEP_TITLES} current={stepIndex(step)} label="Check-in steps" />

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
                     onNext={() => setStep({ kind: "photo", visitor: step.visitor })} />
      )}
      {step.kind === "photo" && (
        <PhotoStep visitor={step.visitor} capturedPhotoId={capturedPhotoId} onCaptured={setCapturedPhotoId}
                   onBack={() => setStep({ kind: "details", visitor: step.visitor })}
                   onNext={(photoId) => setStep({ kind: "review", visitor: step.visitor, photoId })} />
      )}
      {step.kind === "review" && (
        <ReviewStep visitor={step.visitor} draft={draft} photoId={step.photoId}
                    onBack={() => setStep({ kind: "photo", visitor: step.visitor })}
                    // The upload already made this photo the visitor's current one on the server, so after
                    // editing the details the photo step offers to keep it instead of asking for a retake.
                    onEditDetails={() => setStep({ kind: "details",
                      visitor: { ...step.visitor, photo_id: step.photoId ?? step.visitor.photo_id } })}
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
    <Card title="Who is visiting?" description="Enter the ID number from the visitor's identity document."
          icon={<IdCard />} divided={false}>
      <form onSubmit={onSubmit} noValidate className="space-y-6">
        {error && <Alert tone="danger">{error}</Alert>}
        <IdentityInput type={idType} number={idNumber} onType={onType} onNumber={onNumber} error={fieldError}
                       size="lg" autoFocus />
        <div className="flex justify-end">
          <Button type="submit" size="lg" loading={searching} className="w-full sm:w-auto">
            {!searching && <Search aria-hidden="true" />}
            Find visitor
          </Button>
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
    <Card title="New visitor" description="This ID number is not registered yet. Add the visitor's details."
          icon={<UserPlus />} divided={false}>
      <form onSubmit={onSubmit} noValidate className="space-y-6">
        {error && <Alert tone="danger">{error}</Alert>}
        <div className="flex items-center gap-3 rounded-xl border border-border bg-surface-subtle px-4 py-3">
          <IdCard aria-hidden="true" className="size-5 shrink-0 text-ink-muted" />
          <p className="min-w-0">
            <span className="block text-sm text-ink-muted">{IDENTITY_LABELS[idType]}</span>
            <span className="block break-all font-mono text-base font-semibold text-ink">{idNumber}</span>
          </p>
        </div>
        {(errors.identity || errors._form) && <Alert tone="danger">{errors.identity || errors._form}</Alert>}
        <TextField label="Full name" value={name} onChange={(e) => setName(e.target.value)} error={errors.full_name}
                   size="lg" autoComplete="off" autoFocus />
        <TextField label="Phone (optional)" value={phone} onChange={(e) => setPhone(e.target.value)} error={errors.phone}
                   size="lg" inputMode="tel" autoComplete="off" />
        <div className="flex flex-col-reverse gap-3 sm:flex-row sm:justify-between">
          <Button type="button" variant="secondary" size="lg" onClick={onBack}>
            <ArrowLeft aria-hidden="true" />
            Back
          </Button>
          <Button type="submit" size="lg" loading={saving}>Register and continue</Button>
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
    <div className="flex items-center gap-3 rounded-xl border border-border bg-surface-subtle px-4 py-3">
      <Avatar name={visitor.full_name} />
      <div className="min-w-0">
        <p className="truncate text-base font-semibold text-ink" data-testid="visitor-name">{visitor.full_name}</p>
        <p className="text-sm text-ink-muted">
          {visitor.identity && `${IDENTITY_LABELS[visitor.identity.type]} ${visitor.identity.number}`}
          {visitor.phone && ` · ${visitor.phone}`}
        </p>
      </div>
    </div>
  );
}

/** A labelled group of fields inside a step. */
function FieldGroup({ legend, children }: { legend: string; children: React.ReactNode }) {
  return (
    <div className="border-t border-border pt-6">
      <fieldset className="space-y-5">
        <legend className="text-sm font-semibold text-ink">{legend}</legend>
        {children}
      </fieldset>
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
  const set = (changes: Partial<VisitDraft>) => {
    const next = { ...draft, ...changes };
    onChange(next);
    // A shown error disappears as soon as its field is valid; new errors still appear only on Review.
    setErrors((shown) => {
      const now = validateDraft(next);
      return Object.fromEntries(Object.keys(shown).filter((k) => k in now).map((k) => [k, now[k as keyof DraftErrors]]));
    });
  };

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
    <Card title="Visit details" description="Who they are here to see, and why." icon={<ClipboardList />} divided={false}>
      <form onSubmit={onSubmit} noValidate className="space-y-6">
        <VisitorSummary visitor={visitor} />
        <FieldGroup legend="Visiting">
          <div className="space-y-2">
            {draft.unlistedHost ? (
              <TextField label="Name of the person being visited" value={draft.unlistedHostName} autoComplete="off"
                         size="lg" onChange={(e) => set({ unlistedHostName: e.target.value })} error={errors.host}
                         hint="The visit is flagged so an administrator can add this person to the directory." />
            ) : (
              <HostPicker value={draft.host} onChange={(host) => set({ host, departmentId: "" })} error={errors.host} />
            )}
            <Checkbox label="The host is not in the list" checked={draft.unlistedHost}
                      onChange={(e) => set({ unlistedHost: e.target.checked, host: null, departmentId: "" })} />
          </div>
          <SelectField label="Department" value={draft.departmentId} error={errors.department} size="lg"
                       hint={hostDepartment ? "Taken from the host. Change it only if the visit is for another department." : undefined}
                       onChange={(e) => set({ departmentId: e.target.value })}>
            <option value="">{hostDepartment ? `${hostDepartment} (host's department)` : "Choose a department"}</option>
            {departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </SelectField>
        </FieldGroup>
        <FieldGroup legend="Purpose">
          <SelectField label="Reason for visit" value={draft.reason} error={errors.reason} size="lg"
                       onChange={(e) => set({ reason: e.target.value as VisitReason | "" })}>
            <option value="">Choose a reason</option>
            {VISIT_REASONS.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
          </SelectField>
          {draft.reason === "OTHER" && (
            <TextField label="Describe the reason" value={draft.reasonNote} maxLength={200} error={errors.reasonNote}
                       size="lg" onChange={(e) => set({ reasonNote: e.target.value })} />
          )}
        </FieldGroup>
        <FieldGroup legend="Also record (optional)">
          <div className="grid gap-5 sm:grid-cols-2">
            <TextField label="Vehicle registration (optional)" value={draft.vehicle} autoComplete="off" size="lg"
                       onChange={(e) => set({ vehicle: e.target.value })} placeholder="LEA-1234" />
            <TextField label="Belongings (optional)" value={draft.belongings} error={errors.belongings} size="lg"
                       onChange={(e) => set({ belongings: e.target.value })} hint="Separate items with commas." />
          </div>
        </FieldGroup>
        <div className="flex flex-col-reverse gap-3 border-t border-border pt-6 sm:flex-row sm:justify-between">
          <Button type="button" variant="secondary" size="lg" onClick={onCancel}>Cancel</Button>
          <Button type="submit" size="lg">
            Review
            <ArrowRight aria-hidden="true" />
          </Button>
        </div>
      </form>
    </Card>
  );
}

// ---------------------------------------------------------------- step 3: review and confirm
function ReviewStep({ visitor, draft, photoId, onBack, onEditDetails, onDenied, onDone }: {
  visitor: Visitor;
  draft: VisitDraft;
  photoId: string | null;
  onBack: () => void;
  onEditDetails: () => void;
  onDenied: (reason: string) => void;
  onDone: (visit: Visit) => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [problems, setProblems] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [departments, setDepartments] = useState<Department[]>([]);
  const visitorHeading = useId();

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
      onDone(await checkIn({ ...toCheckIn(visitor.id, draft), photo_id: photoId }));
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
  const vehicle = draft.vehicle.trim().toUpperCase();
  const note = draft.reasonNote.trim();
  // Only what the check-in will actually record (the same values toCheckIn sends).
  const visit = [
    { label: "Host", value: draft.unlistedHost ? (
      <span className="flex flex-wrap items-center gap-2">
        {draft.unlistedHostName.trim()}
        <StatusBadge tone="warn">Not in directory</StatusBadge>
      </span>
    ) : draft.host?.name },
    { label: "Department", value: departmentName },
    { label: "Reason", value: draft.reason ? reasonLabel(draft.reason) : "—" },
    ...(note ? [{ label: "Reason details", value: note }] : []),
  ];
  const extra = [
    ...(vehicle ? [{ label: "Vehicle", value: <span className="font-mono">{vehicle}</span> }] : []),
    ...(belongings.length ? [{ label: "Belongings", value: (
      <ul className="flex flex-wrap gap-2">
        {belongings.map((b, i) => (
          <li key={`${b}-${i}`} className="rounded-lg bg-canvas px-2.5 py-1 text-sm font-medium text-ink">{b}</li>
        ))}
      </ul>
    ) }] : []),
  ];

  return (
    <Card title="Confirm check-in" description="Check the details with the visitor before confirming."
          icon={<ClipboardCheck />} divided={false}>
      <div className="space-y-6">
        {error && (
          <Alert tone="danger" title="The visitor was not checked in">
            <p>{error}</p>
            {problems.length > 0 && <ul className="mt-1 list-disc pl-5">{problems.map((p) => <li key={p}>{p}</li>)}</ul>}
          </Alert>
        )}

        <section aria-labelledby={visitorHeading} className="flex flex-col items-center gap-4 rounded-xl border border-border
          bg-surface-subtle p-4 text-center sm:flex-row sm:items-center sm:gap-5 sm:text-left">
          <div className="overflow-hidden rounded-2xl shadow-card">
            <VisitorPhoto photoId={photoId} name={visitor.full_name} className="size-32" />
          </div>
          <div className="min-w-0 flex-1">
            <h3 id={visitorHeading} className="text-heading break-words text-ink">{visitor.full_name}</h3>
            <p className="mt-1 text-base text-ink-muted">
              {visitor.identity ? `${IDENTITY_LABELS[visitor.identity.type]} ${visitor.identity.number}` : "No ID recorded"}
            </p>
            {visitor.phone && <p className="text-base text-ink-muted">{visitor.phone}</p>}
            <Button variant="ghost" size="lg" onClick={onBack} disabled={saving} className="-ml-4 mt-1">
              <Camera aria-hidden="true" />
              {photoId ? "Change photo" : "Add a photo"}
            </Button>
          </div>
        </section>

        <ReviewSection title="Visit" onEdit={onEditDetails} editLabel="Edit visit details" disabled={saving}>
          <DescriptionList items={visit} />
        </ReviewSection>

        {extra.length > 0 && (
          <ReviewSection title="Also recorded" onEdit={onEditDetails} editLabel="Edit vehicle and belongings" disabled={saving}>
            <DescriptionList items={extra} />
          </ReviewSection>
        )}

        <div className="flex flex-col-reverse gap-3 border-t border-border pt-6 sm:flex-row sm:justify-between">
          <Button variant="secondary" size="lg" onClick={onBack} disabled={saving}>
            <ArrowLeft aria-hidden="true" />
            Back
          </Button>
          <Button size="lg" onClick={() => void confirm()} loading={saving}>
            {!saving && <Check aria-hidden="true" />}
            Confirm check-in
          </Button>
        </div>
      </div>
    </Card>
  );
}

/** One group of facts on the review step, with a way back to where they were entered. */
function ReviewSection({ title, onEdit, editLabel, disabled, children }: {
  title: string;
  onEdit: () => void;
  editLabel: string;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-xl border border-border px-4 pb-4 sm:px-5">
      <div className="flex items-center justify-between gap-3 py-1">
        <h3 className="text-sm font-semibold text-ink">{title}</h3>
        <Button variant="ghost" size="lg" onClick={onEdit} disabled={disabled} aria-label={editLabel} className="-mr-3">
          <Pencil aria-hidden="true" />
          Edit
        </Button>
      </div>
      {children}
    </section>
  );
}

/** Checked in: the outcome first, then the badge to print (the main next step), then who and where. */
function DoneStep({ visit, onNext }: { visit: Visit; onNext: () => void }) {
  const headingId = useId();
  const details = [
    { label: "Visiting", value: visit.host_unlisted ? (
      <span className="flex flex-wrap items-center gap-2">
        {visit.host.name}
        <StatusBadge tone="warn">Not in directory</StatusBadge>
      </span>
    ) : visit.host.name },
    ...(visit.department.name ? [{ label: "Department", value: visit.department.name }] : []),
    { label: "Reason", value: reasonLabel(visit.reason_code) },
    { label: "Checked in", value: formatDateTime(visit.check_in_at) },
    { label: "Gate", value: visit.gate.name },
  ];

  return (
    <section aria-labelledby={headingId} data-testid="check-in-done"
             className="rounded-2xl border border-border bg-surface shadow-card">
      <div role="status" className="flex flex-col items-center gap-4 border-b border-border px-6 py-5 text-center
        sm:flex-row sm:text-left">
        <span aria-hidden="true" className="flex size-14 shrink-0 animate-success-in items-center justify-center rounded-full
          bg-ok-bg text-ok ring-8 ring-ok-bg/50">
          <Check className="size-7" strokeWidth={3} />
        </span>
        <div className="min-w-0">
          <h2 id={headingId} className="text-title text-ink">Check-in complete</h2>
          <p className="mt-1 text-base text-ink-muted">{visit.visitor.name} has been checked in.</p>
        </div>
      </div>

      <div className="grid gap-8 p-6 lg:grid-cols-[auto_1fr]">
        <PassCard visit={visit} />

        <div className="min-w-0 space-y-5">
          <div className="flex items-center gap-3">
            {visit.photo_id ? (
              <div className="overflow-hidden rounded-xl">
                <VisitorPhoto photoId={visit.photo_id} name={visit.visitor.name} className="size-14" />
              </div>
            ) : <Avatar name={visit.visitor.name ?? ""} />}
            <p className="text-heading min-w-0 break-words text-ink">{visit.visitor.name}</p>
          </div>
          <div>
            <p className="text-sm text-ink-muted">Visit number</p>
            <p className="font-mono text-2xl font-bold tracking-wide text-ink" data-testid="visit-number">{visit.visit_number}</p>
          </div>
          <DescriptionList items={details} />
          {visit.host_unlisted && (
            <Alert tone="warn">The host is not in the directory; this visit is flagged for review.</Alert>
          )}
        </div>
      </div>

      <div className="flex flex-col gap-3 border-t border-border px-6 py-5 lg:flex-row lg:justify-between">
        <Button variant="secondary" size="lg" onClick={onNext}>
          <UserPlus aria-hidden="true" />
          Check in next visitor
        </Button>
        <ButtonLink href="/check-out" variant="ghost" size="lg">
          <Users aria-hidden="true" />
          Visitors inside
        </ButtonLink>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------- photo
export function PhotoStep({ visitor, capturedPhotoId = null, onCaptured, onBack, onNext }: {
  visitor: Visitor;
  /** A photo uploaded earlier in this same check-in, if any. */
  capturedPhotoId?: string | null;
  onCaptured?: (photoId: string) => void;
  onBack: () => void;
  onNext: (photoId: string | null) => void;
}) {
  const [retaking, setRetaking] = useState(!visitor.photo_id);
  const thisVisit = visitor.photo_id != null && visitor.photo_id === capturedPhotoId;

  async function upload(photo: Blob) {
    const { id } = await uploadVisitorPhoto(visitor.id, photo);
    onCaptured?.(id);
    onNext(id);
  }

  return (
    <Card title="Visitor photo" description="Take a photo of the visitor's face, looking at the camera."
          icon={<Camera />} divided={false}>
      <div className="space-y-6">
        <VisitorSummary visitor={visitor} />
        {visitor.photo_id && !retaking ? (
          <div className="flex flex-col items-center gap-4 text-center">
            <div className="overflow-hidden rounded-2xl shadow-card">
              <VisitorPhoto photoId={visitor.photo_id} name={visitor.full_name} className="size-56" />
            </div>
            <p className="max-w-sm text-base text-ink-muted">
              {thisVisit ? "Photo captured for this visit." : "Photo from an earlier visit. Check that it is the same person."}
            </p>
            <div className="flex w-full flex-col-reverse gap-3 sm:w-auto sm:flex-row">
              <Button variant="secondary" size="lg" onClick={() => setRetaking(true)}>
                <Camera aria-hidden="true" />
                Take a new photo
              </Button>
              <Button size="lg" onClick={() => onNext(visitor.photo_id)}>
                <Check aria-hidden="true" />
                Keep this photo
              </Button>
            </div>
          </div>
        ) : (
          <CameraCapture onConfirm={upload} />
        )}
        <div className="flex flex-col-reverse gap-3 border-t border-border pt-6 sm:flex-row sm:justify-between">
          <Button variant="secondary" size="lg" onClick={onBack}>
            <ArrowLeft aria-hidden="true" />
            Back
          </Button>
          <Button variant="ghost" size="lg" onClick={() => onNext(null)}>Continue without a photo</Button>
        </div>
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------- pass and badge
function PassCard({ visit }: { visit: Visit }) {
  const [issued, setIssued] = useState<IssuedPass | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [issuing, setIssuing] = useState(false);
  const requested = useRef(false);

  const issue = useCallback(async () => {
    setError(null);
    setIssuing(true);
    try {
      setIssued(await issuePass(visit.id));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setIssuing(false);
    }
  }, [visit.id]);

  useEffect(() => {
    // Once per visit (React's development double-run would otherwise issue, and cancel, a first pass).
    if (requested.current) return;
    requested.current = true;
    void issue();
  }, [issue]);

  const headingId = useId();
  return (
    <section aria-labelledby={headingId} className="space-y-4 lg:w-64">
      <h3 id={headingId} className="flex items-center gap-2 text-base font-semibold text-ink">
        {issued ? <><Printer aria-hidden="true" className="size-5 text-brand-700" />Badge ready</>
          : error ? "Badge not issued" : "Preparing the badge…"}
      </h3>
      {error && (
        <div className="space-y-3">
          <Alert tone="danger">The pass could not be issued: {error}</Alert>
          <Button size="lg" className="w-full" onClick={() => void issue()} loading={issuing}>
            {!issuing && <RotateCcw aria-hidden="true" />}
            Try again
          </Button>
        </div>
      )}
      {!error && !issued && (
        <div className="flex justify-center rounded-lg bg-canvas p-4">
          <Skeleton className="h-[86mm] w-[54mm] rounded-[3mm]" />
        </div>
      )}
      {issued && <BadgePreview issued={issued} visitId={visit.id} prominent />}
      <p className="text-sm text-ink-muted">Give the badge to the visitor. Its QR code is used at check-out.</p>
    </section>
  );
}
