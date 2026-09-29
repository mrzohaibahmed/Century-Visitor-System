"use client";

import { Mail, Send, Trash2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Checkbox } from "@/components/ui/Checkbox";
import { DescriptionList } from "@/components/ui/DescriptionList";
import { Modal } from "@/components/ui/Modal";
import { SelectField } from "@/components/ui/SelectField";
import { Skeleton } from "@/components/ui/Skeleton";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { TextField } from "@/components/ui/TextField";
import { ApiError, errorMessage, fieldErrors } from "@/lib/api/client";
import {
  deleteEmailSettings,
  type EmailSettings,
  type EmailSettingsInput,
  type EmailTestResult,
  getEmailSettings,
  saveEmailSettings,
  sendTestEmail,
  type SmtpSecurity,
} from "@/lib/api/emailSettings";

/**
 * Admin → Email settings: the SMTP server used for host notifications. Generic SMTP for any provider.
 * The SMTP password is typed into the form and sent once; it is never shown, prefilled, stored in the
 * browser or put in a URL. The server decides and checks everything; this page only edits and asks.
 */
const SECURITY: { value: SmtpSecurity; label: string; hint: string }[] = [
  { value: "starttls", label: "STARTTLS", hint: "Connects normally, then upgrades to an encrypted connection (usually port 587)." },
  { value: "ssl", label: "SSL/TLS", hint: "Encrypted from the first byte (usually port 465)." },
  { value: "none", label: "None", hint: "Unencrypted. Only for an internal mail relay without a login." },
];

const SOURCE_LABELS: Record<EmailSettings["source"], string> = {
  database: "Saved settings",
  environment: "Server environment",
  none: "Not configured",
};

// Matches what browsers accept for type="email"; the server has the final say.
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function EmailSettingsManager() {
  const [settings, setSettings] = useState<EmailSettings | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const load = useCallback(async () => {
    try {
      setSettings(await getEmailSettings());
      setLoadError(null);
    } catch (e) {
      setLoadError(errorMessage(e));
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- data fetch on mount
    void load();
  }, [load]);

  if (settings === null && !loadError) {
    return (
      <div role="status" className="space-y-4">
        <span className="sr-only">Loading e-mail settings…</span>
        <Skeleton className="h-36 rounded-2xl" />
        <Skeleton className="h-96 rounded-2xl" />
      </div>
    );
  }
  if (settings === null) {
    return (
      <div className="space-y-3">
        <Alert tone="danger" title="The e-mail settings could not be loaded">{loadError}</Alert>
        <Button variant="secondary" onClick={() => void load()}>Try again</Button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <StatusCard settings={settings} onTest={() => setTesting(true)} />
      {/* Keyed by the saved version: a save or delete starts the form again from what the server holds. */}
      <SettingsForm key={`${settings.updated_at ?? "none"}-${settings.saved}`} settings={settings}
                    onSaved={(saved) => { setSettings(saved); toast.success("E-mail settings saved."); }} />
      {settings.saved && (
        <Card title="Delete saved settings" description="Removes the SMTP settings saved here, including the password.">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-sm text-ink-muted">
              {settings.environment_configured
                ? "The server's environment SMTP settings will be used instead."
                : "The server has no environment SMTP settings: e-mail will be off."}
              {" "}To only stop sending, switch e-mail notifications off and save instead.
            </p>
            <Button variant="danger" onClick={() => setDeleting(true)} className="shrink-0">
              <Trash2 aria-hidden="true" />
              Delete saved settings
            </Button>
          </div>
        </Card>
      )}

      <Modal open={testing} onClose={() => setTesting(false)} title="Send a test e-mail"
             description="Uses the settings in use now. Save your changes first to test them.">
        {testing && <TestEmailForm onClose={() => setTesting(false)} />}
      </Modal>
      <Modal open={deleting} onClose={() => setDeleting(false)} title="Delete saved settings?">
        {deleting && (
          <DeleteSettings settings={settings} onCancel={() => setDeleting(false)}
                          onDeleted={() => {
                            setDeleting(false);
                            toast.success("Saved e-mail settings deleted.");
                            void load();
                          }} />
        )}
      </Modal>
    </div>
  );
}

// ---------------------------------------------------------------- status
function StatusCard({ settings: s, onTest }: { settings: EmailSettings; onTest: () => void }) {
  const status = s.source === "database"
    ? (s.enabled ? <StatusBadge tone="ok">Enabled</StatusBadge> : <StatusBadge tone="neutral">Disabled</StatusBadge>)
    : s.source === "environment" ? <StatusBadge tone="ok">Configured</StatusBadge>
      : <StatusBadge tone="neutral">Off</StatusBadge>;
  const password = !s.saved ? "—"
    : s.password_status === "SAVED" ? "Saved"
      : s.password_status === "UNREADABLE" ? "Saved, but cannot be read" : "Not set (no login)";
  return (
    <Card title="Status" icon={<Mail />}
          actions={<Button variant="secondary" onClick={onTest}><Send aria-hidden="true" />Send test e-mail</Button>}>
      <div className="space-y-4">
        <DescriptionList items={[
          { label: "Configuration source", value: <span data-testid="email-source">{SOURCE_LABELS[s.source]}</span> },
          { label: "E-mail notifications", value: <span data-testid="email-status">{status}</span> },
          { label: "Password", value: <span data-testid="email-password-status">{password}</span> },
        ]} />
        {s.source === "environment" && (
          <p className="text-sm text-ink-muted">
            E-mail uses the SMTP settings in the server environment (set by the administrator of the server).
            Saving settings here replaces them for this system.
          </p>
        )}
        {s.source === "none" && (
          <p className="text-sm text-ink-muted">No SMTP server is configured: no e-mail is sent. Enter the settings below.</p>
        )}
        {s.source === "database" && !s.enabled && (
          <Alert tone="info">
            E-mail notifications are switched off. The saved settings stay stored; nothing is sent until they are
            switched on again.
          </Alert>
        )}
        {s.password_status === "UNREADABLE" && (
          <Alert tone="warn" title="The saved password cannot be read">
            It cannot be decrypted with the server&apos;s current key. Enter the password again and save the settings.
          </Alert>
        )}
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------- form
type Draft = { enabled: boolean; host: string; port: string; security: SmtpSecurity; username: string;
  fromEmail: string; fromName: string; replyTo: string };

function draftFrom(s: EmailSettings): Draft {
  return {
    enabled: s.saved ? s.enabled : true, host: s.smtp_host ?? "", port: String(s.smtp_port ?? 587),
    security: s.security ?? "starttls", username: s.username ?? "", fromEmail: s.from_email ?? "",
    fromName: s.from_name ?? "", replyTo: s.reply_to ?? "",
  };
}

export function SettingsForm({ settings, onSaved }: { settings: EmailSettings; onSaved: (saved: EmailSettings) => void }) {
  const [draft, setDraft] = useState<Draft>(() => draftFrom(settings));
  // Only in this form's memory; never prefilled from the server (which never sends it), never stored.
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const busy = useRef(false);
  const set = (change: Partial<Draft>) => setDraft((d) => ({ ...d, ...change }));
  const security = SECURITY.find((o) => o.value === draft.security)!;
  const passwordSaved = settings.saved && settings.password_status === "SAVED";

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (busy.current) return;
    setError(null);
    const port = Number(draft.port.trim());
    const found: Record<string, string> = {};
    if (!draft.host.trim()) found.smtp_host = "Enter the SMTP server's host name or IP address.";
    if (!/^\d+$/.test(draft.port.trim()) || port < 1 || port > 65535) found.smtp_port = "The port is a number from 1 to 65535.";
    if (!EMAIL.test(draft.fromEmail.trim())) found.from_email = "Enter the sender's e-mail address.";
    if (draft.replyTo.trim() && !EMAIL.test(draft.replyTo.trim())) found.reply_to = "Enter a valid e-mail address, or leave it empty.";
    setErrors(found);
    if (Object.keys(found).length) return;

    const input: EmailSettingsInput = {
      enabled: draft.enabled, smtp_host: draft.host.trim(), smtp_port: port, security: draft.security,
      username: draft.username.trim() || null, from_email: draft.fromEmail.trim(),
      from_name: draft.fromName.trim() || null, reply_to: draft.replyTo.trim() || null,
    };
    if (password) input.password = password;       // only when typed: empty keeps the saved one
    busy.current = true;
    setSaving(true);
    try {
      const saved = await saveEmailSettings(input);
      setPassword("");
      onSaved(saved);
    } catch (e) {
      const byField = fieldErrors(e);
      if (e instanceof ApiError && e.code === "email_password_required") byField.password = e.message;
      setErrors(byField);
      setError(e instanceof ApiError && e.code === "email_password_required" ? null : byField._form ?? errorMessage(e));
    } finally {
      busy.current = false;
      setSaving(false);
    }
  }

  return (
    <Card title="SMTP settings"
          description="Works with standard SMTP services, e.g. Gmail / Google Workspace, Microsoft 365 / Outlook, webmail / cPanel, or a company mail server.">
      <form onSubmit={onSubmit} noValidate className="space-y-6">
        {error && <Alert tone="danger">{error}</Alert>}
        <Checkbox label="Send e-mail notifications" checked={draft.enabled} onChange={(e) => set({ enabled: e.target.checked })}
                  hint="When switched off, no e-mail is sent. The settings stay saved." />

        <fieldset className="space-y-4">
          <legend className="text-sm font-semibold tracking-wide text-ink-muted uppercase">SMTP server</legend>
          <TextField label="SMTP host" value={draft.host} onChange={(e) => set({ host: e.target.value })} error={errors.smtp_host}
                     placeholder="smtp.example.com" autoComplete="off" spellCheck={false} />
          <div className="grid gap-4 sm:grid-cols-2">
            <TextField label="SMTP port" value={draft.port} onChange={(e) => set({ port: e.target.value })} error={errors.smtp_port}
                       inputMode="numeric" autoComplete="off" />
            <SelectField label="Security" value={draft.security} error={errors.security} hint={security.hint}
                         onChange={(e) => set({ security: e.target.value as SmtpSecurity })}>
              {SECURITY.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </SelectField>
          </div>
        </fieldset>

        <fieldset className="space-y-4">
          <legend className="text-sm font-semibold tracking-wide text-ink-muted uppercase">Login</legend>
          <TextField label="User name" value={draft.username} onChange={(e) => set({ username: e.target.value })} error={errors.username}
                     autoComplete="off" spellCheck={false}
                     hint="Often the full e-mail address. Leave empty for a relay without a login (the saved password is then removed)." />
          <TextField label="Password" type="password" value={password} onChange={(e) => setPassword(e.target.value)}
                     error={errors.password} autoComplete="new-password" spellCheck={false} maxLength={256}
                     placeholder={passwordSaved ? "Leave unchanged" : undefined}
                     hint={passwordSaved
                       ? "A password is already saved. Enter a new one only to replace it."
                       : "Some providers need an app password here (e.g. Gmail with 2-step verification)."} />
        </fieldset>

        <fieldset className="space-y-4">
          <legend className="text-sm font-semibold tracking-wide text-ink-muted uppercase">Sender</legend>
          <div className="grid gap-4 sm:grid-cols-2">
            <TextField label="From e-mail" type="email" value={draft.fromEmail} onChange={(e) => set({ fromEmail: e.target.value })}
                       error={errors.from_email} autoComplete="off" spellCheck={false} />
            <TextField label="From name (optional)" value={draft.fromName} onChange={(e) => set({ fromName: e.target.value })}
                       error={errors.from_name} placeholder="Century Gate VMS" autoComplete="off" />
          </div>
          <TextField label="Reply-To (optional)" type="email" value={draft.replyTo} onChange={(e) => set({ replyTo: e.target.value })}
                     error={errors.reply_to} autoComplete="off" spellCheck={false}
                     hint="Where replies to notifications go, e.g. the reception desk." />
        </fieldset>

        <div className="flex justify-end border-t border-border pt-5">
          <Button type="submit" loading={saving}>Save settings</Button>
        </div>
      </form>
    </Card>
  );
}

// ---------------------------------------------------------------- test e-mail
function TestEmailForm({ onClose }: { onClose: () => void }) {
  const [to, setTo] = useState("");
  const [invalid, setInvalid] = useState<string | undefined>();
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState<EmailTestResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const busy = useRef(false);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (busy.current) return;
    setResult(null);
    setError(null);
    if (!EMAIL.test(to.trim())) return setInvalid("Enter the e-mail address to send the test to.");
    setInvalid(undefined);
    busy.current = true;
    setSending(true);
    try {
      setResult(await sendTestEmail(to.trim()));
    } catch (e) {
      const byField = fieldErrors(e);
      if (byField.to) setInvalid(byField.to);
      else setError(errorMessage(e));
    } finally {
      busy.current = false;
      setSending(false);
    }
  }

  return (
    <form onSubmit={onSubmit} noValidate className="space-y-4">
      <TextField label="Recipient e-mail" type="email" value={to} onChange={(e) => setTo(e.target.value)} error={invalid}
                 autoComplete="off" spellCheck={false} autoFocus />
      <div aria-live="polite">
        {sending && <p className="text-sm text-ink-muted">Sending test e-mail…</p>}
        {result?.status === "SENT" && <Alert tone="ok">Test e-mail sent successfully. Check the recipient&apos;s inbox.</Alert>}
        {result?.status === "FAILED" && <Alert tone="danger" title="The test e-mail was not sent">{result.message}</Alert>}
        {error && <Alert tone="danger">{error}</Alert>}
      </div>
      <div className="flex justify-end gap-2">
        <Button type="button" variant="secondary" onClick={onClose} disabled={sending}>Close</Button>
        <Button type="submit" loading={sending}>
          {!sending && <Send aria-hidden="true" />}
          Send test e-mail
        </Button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------- delete
function DeleteSettings({ settings, onDeleted, onCancel }: { settings: EmailSettings; onDeleted: () => void; onCancel: () => void }) {
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  async function confirm() {
    if (deleting) return;
    setError(null);
    setDeleting(true);
    try {
      await deleteEmailSettings();
      onDeleted();
    } catch (e) {
      setError(errorMessage(e));
      setDeleting(false);
    }
  }

  return (
    <div className="space-y-4">
      {error && <Alert tone="danger">{error}</Alert>}
      <p className="text-sm text-ink">
        This removes the saved SMTP configuration, including the saved password. It cannot be undone.{" "}
        {settings.environment_configured
          ? "The server's environment SMTP settings will be used instead."
          : "The server has no environment SMTP settings, so e-mail will be off."}
      </p>
      <div className="flex justify-end gap-2">
        <Button variant="secondary" onClick={onCancel} disabled={deleting}>Cancel</Button>
        <Button variant="danger" onClick={() => void confirm()} loading={deleting}>Delete saved settings</Button>
      </div>
    </div>
  );
}
