"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { useSession } from "@/components/session/SessionProvider";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Modal } from "@/components/ui/Modal";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { TextField } from "@/components/ui/TextField";
import { IdentityInput } from "@/components/visits/IdentityInput";
import { VisitTable } from "@/components/visits/VisitTable";
import { usePagedList } from "@/hooks/usePagedList";
import { errorMessage, fieldErrors } from "@/lib/api/client";
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

export function VisitorDetail({ id }: { id: string }) {
  const { hasPermission } = useSession();
  const [data, setData] = useState<VisitorWithStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const visits = usePagedList(id, (cursor) => visitorVisits(id, cursor));

  const load = useCallback(async () => {
    try {
      setData(await getVisitor(id));
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [id]);

  useEffect(() => {
    // Initial load: the result is applied from the async callback.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  if (error) return <Alert tone="danger">{error}</Alert>;
  if (!data) return <p className="text-sm text-ink-muted">Loading…</p>;

  const { visitor, screening } = data;
  const active = visitor.active_visit;
  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <Link href="/visitors" className="text-sm text-brand-700 hover:underline">← Visitors</Link>
          <h1 className="mt-1 text-2xl font-bold text-ink">{visitor.full_name}</h1>
        </div>
        {hasPermission("visitor:edit") && (
          <Button variant="secondary" onClick={() => { setNotice(null); setEditing(true); }}>Edit details</Button>
        )}
      </div>
      <div aria-live="polite">{notice && <Alert tone="ok">{notice}</Alert>}</div>
      {screening.status === "BLOCKED" && (
        <Alert tone="danger">
          <strong>On the watchlist: entry not permitted.</strong>{screening.reason && ` Reason: ${screening.reason}`}
        </Alert>
      )}

      <Card title="Details">
        <dl className="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
          <div><dt className="text-ink-muted">ID</dt>
            <dd className="font-medium">{visitor.identity ? `${IDENTITY_LABELS[visitor.identity.type]} ${visitor.identity.number}` : "—"}</dd></div>
          <div><dt className="text-ink-muted">Phone</dt><dd className="font-medium">{visitor.phone ?? "—"}</dd></div>
          <div><dt className="text-ink-muted">Registered</dt><dd className="font-medium">{formatDateTime(visitor.created_at)}</dd></div>
          <div><dt className="text-ink-muted">Status</dt>
            <dd>{active
              ? <StatusBadge tone="ok">Inside since {formatTime(active.check_in_at)} ({active.visit_number})</StatusBadge>
              : <StatusBadge tone="neutral">Not inside</StatusBadge>}</dd></div>
        </dl>
      </Card>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-ink">Visits</h2>
        {visits.error && <Alert tone="danger">{visits.error}</Alert>}
        <VisitTable visits={visits.items} loading={visits.loading} showVisitor={false} empty="No visits yet." />
        {visits.hasMore && (
          <div className="flex justify-center">
            <Button variant="secondary" onClick={visits.loadMore} loading={visits.loading}>Load more</Button>
          </div>
        )}
      </section>

      <Modal open={editing} title="Edit visitor" onClose={() => setEditing(false)}>
        {editing && (
          <EditVisitorForm visitor={visitor} onCancel={() => setEditing(false)}
                           onDone={(v) => {
                             setEditing(false);
                             setNotice("Visitor details updated.");
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
    const changes: Partial<NewVisitor> = {};
    if (name.trim() !== visitor.full_name) changes.full_name = name.trim();
    if (phone.trim() && phone.trim() !== (visitor.phone ?? "")) changes.phone = phone.trim();
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
    <form onSubmit={onSubmit} noValidate className="space-y-4">
      {(error || errors._form) && <Alert tone="danger">{error || errors._form}</Alert>}
      <TextField label="Full name" value={name} onChange={(e) => setName(e.target.value)} error={errors.full_name} />
      <IdentityInput type={idType} number={idNumber} onType={setIdType} onNumber={setIdNumber} error={errors.identity} />
      <TextField label="Phone" value={phone} onChange={(e) => setPhone(e.target.value)} error={errors.phone} inputMode="tel" />
      <p className="text-xs text-ink-muted">Changes are logged. Past visits keep the name recorded at the time.</p>
      <div className="flex justify-end gap-2">
        <Button type="button" variant="secondary" onClick={onCancel}>Cancel</Button>
        <Button type="submit" loading={saving}>Save changes</Button>
      </div>
    </form>
  );
}
