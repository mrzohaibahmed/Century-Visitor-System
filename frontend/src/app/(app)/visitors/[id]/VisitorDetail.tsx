"use client";

import { ArrowLeft, Pencil, RotateCcw, UserRoundSearch } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { useSession } from "@/components/session/SessionProvider";
import { Alert } from "@/components/ui/Alert";
import { Button, ButtonLink } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { DescriptionList } from "@/components/ui/DescriptionList";
import { Modal } from "@/components/ui/Modal";
import { Skeleton } from "@/components/ui/Skeleton";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { TextField } from "@/components/ui/TextField";
import { IdentityInput } from "@/components/visits/IdentityInput";
import { VisitorPhoto } from "@/components/visits/VisitorPhoto";
import { VisitTable } from "@/components/visits/VisitTable";
import { usePagedList } from "@/hooks/usePagedList";
import { ApiError, errorMessage, fieldErrors } from "@/lib/api/client";
import {
  getVisitor,
  IDENTITY_LABELS,
  type IdentityType,
  type NewVisitor,
  updateVisitor,
  type Visitor,
  type VisitorWithStatus,
  visitorVisits,
} from "@/lib/api/visitors";
import { formatDateTime, formatTime } from "@/lib/format";
import { normalizePhone, phoneError } from "@/lib/phone";

import { VisitorBelongings } from "./VisitorBelongings";

function BackToVisitors() {
  return (
    <ButtonLink href="/visitors" variant="ghost" className="-ml-3">
      <ArrowLeft aria-hidden="true" />
      Visitors
    </ButtonLink>
  );
}

export function VisitorDetail({ id }: { id: string }) {
  const { hasPermission } = useSession();
  const [data, setData] = useState<VisitorWithStatus | null>(null);
  const [error, setError] = useState<{ message: string; notFound: boolean } | null>(null);
  const [editing, setEditing] = useState(false);
  const visits = usePagedList(id, (cursor) => visitorVisits(id, cursor));

  const load = useCallback(async () => {
    setError(null);
    try {
      setData(await getVisitor(id));
    } catch (e) {
      setError({ message: errorMessage(e), notFound: e instanceof ApiError && e.status === 404 });
    }
  }, [id]);

  useEffect(() => {
    // Initial load: the result is applied from the async callback.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  if (error) {
    return (
      <div className="space-y-6">
        <BackToVisitors />
        <div className="flex flex-col items-center gap-3 rounded-2xl border border-border bg-surface px-6 py-12 text-center shadow-card">
          <span aria-hidden="true" className="flex size-12 items-center justify-center rounded-full bg-surface-subtle text-ink-muted">
            <UserRoundSearch className="size-6" />
          </span>
          <h1 className="text-heading text-ink">{error.notFound ? "Visitor not found" : "Unable to load this visitor"}</h1>
          <p role="alert" className="max-w-sm text-sm text-ink-muted">
            {error.notFound ? "There is no visitor record at this address. Search for the visitor instead." : error.message}
          </p>
          {!error.notFound && (
            <Button variant="secondary" onClick={() => void load()}>
              <RotateCcw aria-hidden="true" />
              Try again
            </Button>
          )}
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div role="status" className="space-y-6">
        <span className="sr-only">Loading visitor…</span>
        <Skeleton className="h-11 w-28" />
        <div className="flex items-center gap-5 rounded-2xl border border-border bg-surface p-6 shadow-card">
          <Skeleton className="size-28 rounded-2xl" />
          <div className="flex-1 space-y-3">
            <Skeleton className="h-8 w-2/3" />
            <Skeleton className="h-4 w-1/3" />
            <Skeleton className="h-6 w-28 rounded-full" />
          </div>
        </div>
        <Skeleton className="h-40 rounded-2xl" />
      </div>
    );
  }

  const { visitor, screening } = data;
  const active = visitor.active_visit;
  const details = [
    { label: "ID", value: visitor.identity
      ? <><span className="text-ink-muted">{IDENTITY_LABELS[visitor.identity.type]} </span><span className="font-mono break-all">{visitor.identity.number}</span></>
      : <span className="text-ink-muted">No ID recorded</span> },
    ...(visitor.phone ? [{ label: "Phone", value: visitor.phone }] : []),
    ...(active ? [{ label: "Current visit", value: (
      <>Inside since {formatTime(active.check_in_at)}{active.gate_name && <> at <span className="caps">{active.gate_name}</span></>}
        <span className="font-mono text-ink-muted"> ({active.visit_number})</span></>
    ) }] : []),
    { label: "Registered", value: formatDateTime(visitor.created_at) },
    { label: "Last updated", value: formatDateTime(visitor.updated_at) },
  ];

  return (
    <div className="space-y-6">
      <BackToVisitors />

      <section className="flex flex-col gap-5 rounded-2xl border border-border bg-surface p-5 shadow-card sm:flex-row sm:items-center sm:p-6">
        <div className="shrink-0 self-start overflow-hidden rounded-2xl sm:self-auto">
          <VisitorPhoto photoId={visitor.photo_id} name={visitor.full_name} className="size-24 sm:size-28" />
        </div>
        <div className="min-w-0 flex-1">
          <h1 className="caps text-title break-words text-ink">{visitor.full_name}</h1>
          {visitor.identity && (
            <p className="mt-1 text-ink-muted">
              {IDENTITY_LABELS[visitor.identity.type]} <span className="font-mono break-all text-ink">{visitor.identity.number}</span>
            </p>
          )}
          <div className="mt-3 flex flex-wrap gap-2">
            {active
              ? <StatusBadge tone="ok">Inside since {formatTime(active.check_in_at)} ({active.visit_number})</StatusBadge>
              : <StatusBadge tone="neutral">Not inside</StatusBadge>}
            {screening.status === "BLOCKED" && <StatusBadge tone="danger">On the watchlist</StatusBadge>}
          </div>
        </div>
        {hasPermission("visitor:edit") && (
          <Button variant="secondary" size="lg" onClick={() => setEditing(true)} className="shrink-0">
            <Pencil aria-hidden="true" />
            Edit details
          </Button>
        )}
      </section>

      {screening.status === "BLOCKED" && (
        <Alert tone="danger">
          <strong>On the watchlist: entry not permitted.</strong>{screening.reason && ` Reason: ${screening.reason}`}
        </Alert>
      )}

      <Card title="Details" divided={false}>
        <DescriptionList items={details} />
      </Card>

      {active && <VisitorBelongings visitId={active.id} />}

      <section aria-labelledby="visits-heading" className="space-y-3">
        <h2 id="visits-heading" className="text-heading text-ink">Visits</h2>
        {visits.error && (
          <Alert tone="danger" title="Unable to load the visits">
            <p>{visits.error}</p>
            <button type="button" onClick={visits.reload} className="mt-1 font-semibold underline underline-offset-2">Try again</button>
          </Alert>
        )}
        {!(visits.error && visits.items.length === 0) && (
          <VisitTable visits={visits.items} loading={visits.loading} showVisitor={false} empty="No visits yet." />
        )}
        {visits.hasMore && (
          <div className="flex justify-center">
            <Button variant="secondary" size="lg" onClick={visits.loadMore} loading={visits.loading}>Load more</Button>
          </div>
        )}
      </section>

      <Modal open={editing} title="Edit visitor" onClose={() => setEditing(false)}>
        {editing && (
          <EditVisitorForm visitor={visitor} onCancel={() => setEditing(false)}
                           onDone={(v) => {
                             setEditing(false);
                             toast.success("Visitor details updated.");
                             setData({ ...data, visitor: v });
                             visits.reload();
                           }} />
        )}
      </Modal>
    </div>
  );
}

export function EditVisitorForm({ visitor, onDone, onCancel }: {
  visitor: Visitor;
  onDone: (v: Visitor) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(visitor.full_name);
  const [phone, setPhone] = useState(visitor.phone ?? "");
  const [idType, setIdType] = useState<IdentityType>(visitor.identity?.type ?? "CNIC");
  const [idNumber, setIdNumber] = useState(visitor.identity?.number ?? "");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setErrors({});
    const invalidPhone = phoneError(phone);
    if (invalidPhone) {
      setErrors({ phone: invalidPhone });
      return;
    }
    const changes: Partial<NewVisitor> = {};
    if (name.trim() !== visitor.full_name) changes.full_name = name.trim();
    const normalizedPhone = normalizePhone(phone);
    if (normalizedPhone && normalizedPhone !== visitor.phone) changes.phone = normalizedPhone;
    if (idType !== visitor.identity?.type || idNumber.trim() !== visitor.identity?.number) {
      changes.identity = { type: idType, number: idNumber.trim() };
    }
    if (Object.keys(changes).length === 0) return onCancel();
    setSaving(true);
    try {
      onDone(await updateVisitor(visitor.id, changes));
    } catch (e) {
      const byField = fieldErrors(e);
      if (Object.keys(byField).length) setErrors(byField);
      else setError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={onSubmit} noValidate className="space-y-5">
      {(error || errors._form) && <Alert tone="danger">{error || errors._form}</Alert>}
      <TextField label="Full name" value={name} onChange={(e) => setName(e.target.value)} error={errors.full_name} caps />
      <IdentityInput type={idType} number={idNumber} onType={setIdType} onNumber={setIdNumber} error={errors.identity} />
      <TextField label="Phone" value={phone} onChange={(e) => {
        setPhone(e.target.value);
        if (errors.phone) setErrors((current) => ({ ...current, phone: "" }));
      }} error={errors.phone} inputMode="tel" autoComplete="tel"
      hint="Use 03XX-XXXXXXX or +92 3XX XXXXXXX." />
      <p className="text-sm text-ink-muted">Changes are logged. Past visits keep the name recorded at the time.</p>
      <div className="flex flex-col-reverse gap-3 pt-1 sm:flex-row sm:justify-end">
        <Button type="button" variant="secondary" size="lg" onClick={onCancel}>Cancel</Button>
        <Button type="submit" size="lg" loading={saving}>Save changes</Button>
      </div>
    </form>
  );
}
