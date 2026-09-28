"use client";

import { useEffect, useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { selectGate } from "@/lib/api/auth";
import { errorMessage } from "@/lib/api/client";
import { type Gate, listGates } from "@/lib/api/directory";

import { useSession } from "./SessionProvider";

/**
 * Shows the gate this session works at, and asks for one when several gates
 * exist and none is chosen (every check-in / check-out records the gate).
 */
export function GatePicker() {
  const { me, replace } = useSession();
  // A forced password change comes first: the API allows nothing else until then.
  const required = me.session.gate_selection_required && !me.user.must_change_password;
  const [changing, setChanging] = useState(false);
  const open = required || changing;

  return (
    <>
      {me.session.gate && (
        <div className="flex items-center gap-2 text-sm">
          <span className="text-ink-muted">Gate:</span>
          <span className="font-semibold text-ink" data-testid="current-gate">{me.session.gate.name}</span>
          <Button variant="ghost" className="min-h-8 px-2 py-1" onClick={() => setChanging(true)}>Change</Button>
        </div>
      )}
      <Modal open={open} title="Which gate are you at?" dismissible={!required}
             onClose={() => { if (!required) setChanging(false); }}>
        {open && (
          <GateChoice current={me.session.gate?.id ?? null} onCancel={required ? undefined : () => setChanging(false)}
                      onChosen={async (gateId) => { replace(await selectGate(gateId)); setChanging(false); }} />
        )}
      </Modal>
    </>
  );
}

export function GateChoice({ current, onChosen, onCancel }: {
  current: string | null;
  onChosen: (gateId: string) => Promise<void>;
  onCancel?: () => void;
}) {
  const [gates, setGates] = useState<Gate[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    listGates(false, controller.signal).then(setGates).catch((e) => {
      if (!controller.signal.aborted) setError(errorMessage(e));
    });
    return () => controller.abort();
  }, []);

  async function choose(gateId: string) {
    setError(null);
    setSaving(gateId);
    try {
      await onChosen(gateId);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSaving(null);
    }
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-ink-muted">Every check-in and check-out you record is logged against this gate.</p>
      {error && <Alert tone="danger">{error}</Alert>}
      {gates === null && !error && <p className="text-sm text-ink-muted">Loading gates…</p>}
      {gates?.length === 0 && <Alert tone="warn">No gates are set up. Ask an administrator to add one.</Alert>}
      <ul className="space-y-2">
        {gates?.map((g) => (
          <li key={g.id}>
            <Button variant={g.id === current ? "primary" : "secondary"} className="w-full justify-between"
                    loading={saving === g.id} disabled={saving !== null} onClick={() => void choose(g.id)}>
              <span>{g.name}</span>
              {g.location && <span className="text-xs font-normal opacity-75">{g.location}</span>}
            </Button>
          </li>
        ))}
      </ul>
      {onCancel && (
        <div className="flex justify-end">
          <Button variant="secondary" onClick={onCancel}>Cancel</Button>
        </div>
      )}
    </div>
  );
}
