"use client";

import { Camera, Cctv, DoorClosed, Pencil, PlugZap, Trash2 } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Alert } from "@/components/ui/Alert";
import { Button, buttonClasses } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Checkbox } from "@/components/ui/Checkbox";
import { DescriptionList } from "@/components/ui/DescriptionList";
import { Modal } from "@/components/ui/Modal";
import { SelectField } from "@/components/ui/SelectField";
import { Skeleton } from "@/components/ui/Skeleton";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { TextField } from "@/components/ui/TextField";
import { errorMessage, fieldErrors } from "@/lib/api/client";
import {
  captureTestPhoto,
  type CameraProtocol,
  type GateCamera,
  type GateCameraInput,
  listGateCameras,
  removeGateCamera,
  saveGateCamera,
  testGateCamera,
} from "@/lib/api/gateCameras";
import { caps, formatDateTime } from "@/lib/format";

/**
 * Admin → Gate cameras: one card per gate. The server talks to the cameras; this page only edits
 * settings and asks the server to test. The camera password is typed into the form and sent once;
 * it is never shown, prefilled, stored in the browser or put in a URL.
 */
export function GateCamerasManager() {
  const [cameras, setCameras] = useState<GateCamera[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editing, setEditing] = useState<GateCamera | null>(null);
  const [removing, setRemoving] = useState<GateCamera | null>(null);
  const [photo, setPhoto] = useState<{ camera: GateCamera; url: string; note: string } | null>(null);

  const load = useCallback(async () => {
    try {
      setCameras(await listGateCameras());
      setLoadError(null);
    } catch (e) {
      setLoadError(errorMessage(e));
    }
  }, []);

  useEffect(() => {
    // Loaded once when the page opens; cameras are never tested or polled automatically.
    // eslint-disable-next-line react-hooks/set-state-in-effect -- data fetch on mount
    void load();
  }, [load]);

  const closePhoto = useCallback(() => {
    setPhoto((current) => {
      if (current) URL.revokeObjectURL(current.url);        // the picture only ever lived in memory
      return null;
    });
  }, []);
  useEffect(() => () => closePhoto(), [closePhoto]);

  if (cameras === null && !loadError) {
    return (
      <div role="status" className="grid gap-4 lg:grid-cols-2">
        <span className="sr-only">Loading gate cameras…</span>
        {[0, 1].map((i) => <Skeleton key={i} className="h-72 rounded-2xl" />)}
      </div>
    );
  }
  if (cameras === null) {
    return (
      <div className="space-y-3">
        <Alert tone="danger" title="The gate cameras could not be loaded">{loadError}</Alert>
        <Button variant="secondary" onClick={() => void load()}>Try again</Button>
      </div>
    );
  }
  if (cameras.length === 0) {
    return (
      <Card>
        <div className="flex flex-col items-center gap-3 py-6 text-center">
          <span aria-hidden="true" className="flex size-12 items-center justify-center rounded-full bg-surface-subtle text-ink-muted">
            <DoorClosed className="size-6" />
          </span>
          <p className="font-medium text-ink">No gates yet</p>
          <p className="max-w-sm text-sm text-ink-muted">A camera belongs to a gate. Add the gates first, then set up their cameras here.</p>
          <Link href="/directory/gates" className={buttonClasses({ variant: "secondary" })}>Go to gates</Link>
        </div>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      {loadError && <Alert tone="danger">{loadError}</Alert>}
      <div className="grid gap-4 lg:grid-cols-2">
        {cameras.map((c) => (
          <GateCameraCard key={c.gate_id} camera={c} onEdit={() => setEditing(c)} onRemove={() => setRemoving(c)}
                          onChanged={load}
                          onPhoto={(url, note) => { closePhoto(); setPhoto({ camera: c, url, note }); }} />
        ))}
      </div>

      <Modal open={editing !== null} onClose={() => setEditing(null)}
             title={editing?.configured ? "Edit camera" : "Set up camera"}
             description={editing ? `Gate: ${caps(editing.gate_name)}` : undefined}>
        {editing && (
          <CameraForm camera={editing} onCancel={() => setEditing(null)}
                      onSaved={(saved) => {
                        setEditing(null);
                        toast.success(`Camera settings saved for ${caps(saved.gate_name)}.`);
                        void load();
                      }} />
        )}
      </Modal>

      <Modal open={removing !== null} onClose={() => setRemoving(null)} title="Remove camera?">
        {removing && (
          <RemoveCamera camera={removing} onCancel={() => setRemoving(null)}
                        onRemoved={() => {
                          toast.success(`Camera removed from ${caps(removing.gate_name)}.`);
                          setRemoving(null);
                          void load();
                        }} />
        )}
      </Modal>

      <Modal open={photo !== null} onClose={closePhoto} title="Test photo"
             description={photo ? `From the ${caps(photo.camera.gate_name)} camera.` : undefined}>
        {photo && (
          <div className="space-y-4">
            <p className="rounded-lg bg-warn-bg px-3 py-2 text-center text-sm font-bold tracking-wide text-warn" data-testid="test-photo-label">
              TEST PHOTO — NOT STORED
            </p>
            {/* eslint-disable-next-line @next/next/no-img-element -- in-memory blob from the server, never an asset */}
            <img src={photo.url} alt={`Test photo from the ${caps(photo.camera.gate_name)} camera (not stored)`}
                 className="w-full rounded-xl border border-border bg-canvas object-contain" data-testid="test-photo" />
            {photo.note && <p className="text-sm text-ink-muted">{photo.note}</p>}
            <div className="flex justify-end"><Button onClick={closePhoto}>Close</Button></div>
          </div>
        )}
      </Modal>
    </div>
  );
}

// ---------------------------------------------------------------- one gate
function GateCameraCard({ camera: c, onEdit, onRemove, onChanged, onPhoto }: {
  camera: GateCamera;
  onEdit: () => void;
  onRemove: () => void;
  onChanged: () => Promise<void>;
  onPhoto: (url: string, note: string) => void;
}) {
  const [busy, setBusy] = useState<"test" | "photo" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const running = useRef(false);                     // one request at a time, even on a double click
  const usable = c.configured && c.password_status === "SAVED";

  async function run(kind: "test" | "photo") {
    if (running.current) return;
    running.current = true;
    setBusy(kind);
    setError(null);
    try {
      if (kind === "test") {
        await testGateCamera(c.gate_id);             // the result is saved on the server as the last test
        await onChanged();
      } else {
        const shot = await captureTestPhoto(c.gate_id);
        const note = [shot.cameraSize && `Camera picture ${shot.cameraSize[0]} × ${shot.cameraSize[1]} px.`,
          shot.photoSize && `A visitor photo from this camera is kept at ${shot.photoSize[0]} × ${shot.photoSize[1]} px.`]
          .filter(Boolean).join(" ");
        onPhoto(URL.createObjectURL(shot.blob), note);
      }
    } catch (e) {
      setError(errorMessage(e));                     // the API's safe message only
    } finally {
      running.current = false;
      setBusy(null);
    }
  }

  return (
    <Card title={c.gate_name} icon={<Cctv />} className="[&_h2]:caps" divided
          description={c.gate_active ? undefined : "This gate is inactive."}
          actions={<CameraBadge camera={c} />}
          footer={c.configured ? (
            <>
              <Button variant="ghost" onClick={onRemove} disabled={busy !== null}>
                <Trash2 aria-hidden="true" />Remove
              </Button>
              <Button variant="secondary" onClick={onEdit} disabled={busy !== null}>
                <Pencil aria-hidden="true" />Edit
              </Button>
              <Button variant="secondary" onClick={() => void run("photo")} disabled={!usable || busy === "test"}
                      loading={busy === "photo"} aria-label={`Capture test photo, ${c.gate_name}`}>
                {busy !== "photo" && <Camera aria-hidden="true" />}Capture test photo
              </Button>
              <Button onClick={() => void run("test")} disabled={!usable || busy === "photo"} loading={busy === "test"}
                      aria-label={`Test connection, ${c.gate_name}`}>
                {busy !== "test" && <PlugZap aria-hidden="true" />}Test connection
              </Button>
            </>
          ) : (
            <Button onClick={onEdit}>Set up camera</Button>
          )}>
      <div className="space-y-4" aria-busy={busy !== null || undefined}>
        {!c.configured && <p className="text-sm text-ink-muted">No camera is set up for this gate.</p>}
        {c.configured && (
          <DescriptionList items={[
            { label: "Connection", value: <span className="font-mono text-sm">{connectionText(c)}</span> },
            { label: "Channel", value: c.channel },
            { label: "User name", value: c.username },
            { label: "Password", value: <PasswordState status={c.password_status} /> },
            { label: "Timeout", value: `${c.timeout_seconds} s` },
          ]} />
        )}
        {c.configured && <LastTest camera={c} />}
        {c.password_status === "UNREADABLE" && (
          <Alert tone="warn" title="The saved password cannot be read">
            The server&apos;s encryption key has changed since it was saved. Edit the camera and enter the password again.
          </Alert>
        )}
        {busy && (
          <p role="status" className="text-sm text-ink-muted">
            {busy === "test" ? "Testing the camera…" : "Taking a test photo…"}
          </p>
        )}
        {error && <Alert tone="danger">{error}</Alert>}
      </div>
    </Card>
  );
}

function connectionText(c: GateCamera): string {
  const port = c.port ?? (c.protocol === "https" ? 443 : 80);
  return `${(c.protocol ?? "").toUpperCase()} · ${c.host}:${port}`;
}

function CameraBadge({ camera: c }: { camera: GateCamera }) {
  if (!c.configured) return <StatusBadge tone="neutral">Not set up</StatusBadge>;
  return c.enabled ? <StatusBadge tone="ok">Enabled</StatusBadge> : <StatusBadge tone="neutral">Disabled</StatusBadge>;
}

function PasswordState({ status }: { status: GateCamera["password_status"] }) {
  if (status === "SAVED") return <span data-testid="password-state">•••••••• (saved)</span>;
  if (status === "UNREADABLE") return <span className="text-warn" data-testid="password-state">Saved, but cannot be read</span>;
  return <span className="text-ink-muted" data-testid="password-state">No password saved</span>;
}

function LastTest({ camera: c }: { camera: GateCamera }) {
  const t = c.last_test;
  return (
    <div className="rounded-xl border border-border bg-surface-subtle px-4 py-3 text-sm" data-testid="last-test">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-ink-muted">Last test</span>
        {c.password_status === "UNREADABLE" ? <StatusBadge tone="danger">Unreadable password</StatusBadge>
          : !t ? <StatusBadge tone="neutral">Not tested</StatusBadge>
            : t.ok ? <StatusBadge tone="ok">Connected</StatusBadge> : <StatusBadge tone="danger">Failed</StatusBadge>}
        {t && <span className="text-ink-muted">{formatDateTime(t.tested_at)}</span>}
      </div>
      {t?.ok && (t.model || t.firmware) && (
        <p className="mt-1 text-ink">
          {t.model && <>Model <span className="font-mono">{t.model}</span></>}
          {t.model && t.firmware && " · "}
          {t.firmware && <>Firmware <span className="font-mono">{t.firmware}</span></>}
        </p>
      )}
      {t && !t.ok && t.message && <p className="mt-1 text-ink">{t.message}</p>}
    </div>
  );
}

// ---------------------------------------------------------------- set up / edit
type Draft = { enabled: boolean; host: string; protocol: CameraProtocol; port: string; channel: string;
  username: string; timeout: string };

const DESTINATION_LABELS = "address, connection, port or user name";

function draftFrom(c: GateCamera): Draft {
  return {
    enabled: c.configured ? c.enabled : true, host: c.host ?? "", protocol: c.protocol ?? "https",
    port: c.port != null ? String(c.port) : "", channel: String(c.channel ?? 101), username: c.username ?? "",
    timeout: String(c.timeout_seconds ?? 5),
  };
}

function wholeNumber(text: string, min: number, max: number): number | null {
  const n = Number(text.trim());
  return /^\d+$/.test(text.trim()) && n >= min && n <= max ? n : null;
}

export function CameraForm({ camera, onSaved, onCancel }: {
  camera: GateCamera;
  onSaved: (saved: GateCamera) => void;
  onCancel: () => void;
}) {
  const initial = draftFrom(camera);
  const [draft, setDraft] = useState<Draft>(initial);
  // Only in this form's memory while it is open; never prefilled, never stored.
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const set = (change: Partial<Draft>) => setDraft((d) => ({ ...d, ...change }));
  const destinationChanged = camera.configured && (draft.host.trim() !== initial.host || draft.protocol !== initial.protocol
    || draft.port.trim() !== initial.port || draft.username.trim() !== initial.username);
  const passwordNeeded = !camera.configured || camera.password_status !== "SAVED" || destinationChanged;

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    const port = draft.port.trim() ? wholeNumber(draft.port, 1, 65535) : null;
    const channel = wholeNumber(draft.channel, 1, 65535);
    const timeout = Number(draft.timeout);
    const found: Record<string, string> = {};
    if (!draft.host.trim()) found.host = "Enter the camera's IP address or host name.";
    if (draft.port.trim() && port === null) found.port = "The port is a number from 1 to 65535.";
    if (channel === null) found.channel = "The channel is a number from 1 to 65535.";
    if (!draft.username.trim()) found.username = "Enter the camera user name.";
    if (!(timeout >= 1 && timeout <= 30)) found.timeout_seconds = "The timeout is 1 to 30 seconds.";
    if (passwordNeeded && !password) {
      found.password = destinationChanged
        ? `You changed the ${DESTINATION_LABELS}: enter the camera password again.` : "Enter the camera password.";
    }
    setErrors(found);
    if (Object.keys(found).length) return;

    const input: GateCameraInput = {
      enabled: draft.enabled, host: draft.host.trim(), protocol: draft.protocol, port, channel: channel!,
      username: draft.username.trim(), timeout_seconds: timeout,
    };
    if (password) input.password = password;       // only sent when typed; empty keeps the saved one
    setSaving(true);
    try {
      const saved = await saveGateCamera(camera.gate_id, input);
      setPassword("");
      onSaved(saved);
    } catch (e) {
      const byField = fieldErrors(e);
      const code = (e as { code?: string }).code;
      if (code === "camera_password_required") byField.password = errorMessage(e);
      setErrors(byField);
      setError(code === "camera_password_required" ? null : byField._form ?? errorMessage(e));
    } finally {
      setSaving(false);
    }
  }

  const passwordHint = passwordNeeded
    ? destinationChanged ? `Required again: you changed the ${DESTINATION_LABELS}.` : "Required."
    : "Leave empty to keep the saved password.";

  return (
    <form onSubmit={onSubmit} noValidate className="space-y-4">
      {error && <Alert tone="danger">{error}</Alert>}
      <Checkbox label="Use this camera for visitor photos at this gate" checked={draft.enabled}
                onChange={(e) => set({ enabled: e.target.checked })}
                hint="Check-in keeps using the webcam until camera capture is added to check-in." />
      <TextField label="Camera address" value={draft.host} onChange={(e) => set({ host: e.target.value })} error={errors.host}
                 placeholder="IP address or host name" autoComplete="off" spellCheck={false} autoFocus />
      <div className="grid gap-4 sm:grid-cols-2">
        <SelectField label="Connection" value={draft.protocol} error={errors.protocol}
                     onChange={(e) => set({ protocol: e.target.value as CameraProtocol })}
                     hint={draft.protocol === "http" ? "Only on a camera network the server alone can reach." : undefined}>
          <option value="https">HTTPS</option>
          <option value="http">HTTP</option>
        </SelectField>
        <TextField label="Port" value={draft.port} onChange={(e) => set({ port: e.target.value })} error={errors.port}
                   inputMode="numeric" autoComplete="off" placeholder={draft.protocol === "https" ? "443" : "80"}
                   hint="Empty: the standard port." />
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <TextField label="Channel" value={draft.channel} onChange={(e) => set({ channel: e.target.value })} error={errors.channel}
                   inputMode="numeric" autoComplete="off" hint="Often 101 (channel 1, main stream). Check the camera." />
        <TextField label="Timeout (seconds)" value={draft.timeout} onChange={(e) => set({ timeout: e.target.value })}
                   error={errors.timeout_seconds} inputMode="decimal" autoComplete="off" />
      </div>
      <TextField label="Camera user name" value={draft.username} onChange={(e) => set({ username: e.target.value })}
                 error={errors.username} autoComplete="off" spellCheck={false}
                 hint="Use a camera account that may only take pictures, not the camera's admin account." />
      <TextField label="Camera password" type="password" value={password} onChange={(e) => setPassword(e.target.value)}
                 error={errors.password} autoComplete="new-password" spellCheck={false} maxLength={128}
                 placeholder={camera.password_status === "SAVED" && !destinationChanged ? "•••••••• (saved)" : undefined}
                 hint={passwordHint} />
      <div className="flex justify-end gap-2">
        <Button type="button" variant="secondary" onClick={onCancel}>Cancel</Button>
        <Button type="submit" loading={saving}>Save camera</Button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------- remove
function RemoveCamera({ camera, onRemoved, onCancel }: { camera: GateCamera; onRemoved: () => void; onCancel: () => void }) {
  const [error, setError] = useState<string | null>(null);
  const [removing, setRemoving] = useState(false);

  async function confirm() {
    setError(null);
    setRemoving(true);
    try {
      await removeGateCamera(camera.gate_id);
      onRemoved();
    } catch (e) {
      setError(errorMessage(e));
      setRemoving(false);
    }
  }

  return (
    <div className="space-y-4">
      {error && <Alert tone="danger">{error}</Alert>}
      <p className="text-sm text-ink">
        The camera settings of <strong className="caps">{camera.gate_name}</strong>, including the saved camera password,
        will be deleted. This cannot be undone: to use the camera again, set it up and enter the password again.
      </p>
      <div className="flex justify-end gap-2">
        <Button variant="secondary" onClick={onCancel} disabled={removing}>Cancel</Button>
        <Button variant="danger" onClick={() => void confirm()} loading={removing}>Remove camera</Button>
      </div>
    </div>
  );
}
