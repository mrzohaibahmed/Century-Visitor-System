"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { useSession } from "@/components/session/SessionProvider";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { TextField } from "@/components/ui/TextField";
import { changePassword } from "@/lib/api/auth";
import { ApiError } from "@/lib/api/client";

export const PASSWORD_HINT = "At least 10 characters. Must not contain the username or be a common password.";

export function ChangePasswordForm() {
  const { user, refresh } = useSession();
  const router = useRouter();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const mismatch = confirm.length > 0 && next !== confirm;

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    if (!current || !next) return setError("Fill in all fields.");
    if (next !== confirm) return setError("The new passwords do not match.");
    setSubmitting(true);
    try {
      await changePassword(current, next);
      setDone(true);
      setCurrent(""); setNext(""); setConfirm("");
      const wasRequired = user.must_change_password;
      await refresh();
      if (wasRequired) router.replace("/dashboard");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={onSubmit} noValidate className="space-y-4 rounded-xl border border-border bg-surface p-6 shadow-sm">
      {user.must_change_password && !done && (
        <Alert tone="warn">Your password was set by an administrator. Choose your own password to continue.</Alert>
      )}
      {done && <Alert tone="ok">Your password has been changed.</Alert>}
      {error && <Alert tone="danger">{error}</Alert>}
      <TextField label="Current password" type="password" autoComplete="current-password"
                 value={current} onChange={(e) => setCurrent(e.target.value)} />
      <TextField label="New password" type="password" autoComplete="new-password" hint={PASSWORD_HINT}
                 value={next} onChange={(e) => setNext(e.target.value)} />
      <TextField label="Confirm new password" type="password" autoComplete="new-password"
                 error={mismatch ? "The passwords do not match." : undefined}
                 value={confirm} onChange={(e) => setConfirm(e.target.value)} />
      <Button type="submit" loading={submitting}>Change password</Button>
    </form>
  );
}
