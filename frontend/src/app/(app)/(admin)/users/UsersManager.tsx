"use client";

import { useCallback, useEffect, useState } from "react";

import { useSession } from "@/components/session/SessionProvider";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { TextField } from "@/components/ui/TextField";
import type { Role, User } from "@/lib/api/auth";
import { ApiError } from "@/lib/api/client";
import { createUser, listUsers, resetPassword, unlockUser, updateUser } from "@/lib/api/users";

import { PASSWORD_HINT } from "../../account/password/ChangePasswordForm";

const ROLE_LABELS: Record<Role, string> = { ADMIN: "Administrator", GUARD: "Guard" };

type Dialog = { kind: "create" } | { kind: "edit"; user: User } | { kind: "reset"; user: User } | null;

function message(e: unknown) {
  return e instanceof ApiError ? e.message : "Something went wrong. Please try again.";
}

function RoleSelect({ value, onChange, disabled }: { value: Role; onChange: (r: Role) => void; disabled?: boolean }) {
  return (
    <div>
      <label htmlFor="role" className="mb-1 block text-sm font-medium text-ink">Role</label>
      <select id="role" value={value} disabled={disabled} onChange={(e) => onChange(e.target.value as Role)}
              className="block min-h-11 w-full rounded-lg border border-border bg-surface px-3 text-base text-ink">
        <option value="GUARD">Guard — check visitors in and out</option>
        <option value="ADMIN">Administrator — full access</option>
      </select>
    </div>
  );
}

export function UsersManager() {
  const { user: me } = useSession();
  const [users, setUsers] = useState<User[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [dialog, setDialog] = useState<Dialog>(null);

  const load = useCallback(async () => {
    try {
      setUsers((await listUsers()).items);
      setLoadError(null);
    } catch (e) {
      setLoadError(message(e));
    }
  }, []);

  useEffect(() => {
    // Initial load: the result is applied from the async callback.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  const finish = (text: string) => {
    setDialog(null);
    setNotice(text);
    void load();
  };

  async function unlock(user: User) {
    try {
      await unlockUser(user.id);
      finish(`${user.username} has been unlocked.`);
    } catch (e) {
      setNotice(null);
      setLoadError(message(e));
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div aria-live="polite">{notice && <Alert tone="ok">{notice}</Alert>}</div>
        <Button onClick={() => { setNotice(null); setDialog({ kind: "create" }); }}>New user</Button>
      </div>
      {loadError && <Alert tone="danger">{loadError}</Alert>}

      <div className="overflow-hidden rounded-xl border border-border bg-surface shadow-sm">
        <table className="w-full text-left text-sm">
          <thead className="bg-canvas text-xs uppercase tracking-wide text-ink-muted">
            <tr>
              <th scope="col" className="px-4 py-3">User</th>
              <th scope="col" className="px-4 py-3">Role</th>
              <th scope="col" className="px-4 py-3">Status</th>
              <th scope="col" className="px-4 py-3">Last login</th>
              <th scope="col" className="px-4 py-3"><span className="sr-only">Actions</span></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {users === null && !loadError && (
              <tr><td colSpan={5} className="px-4 py-8 text-center text-ink-muted">Loading users…</td></tr>
            )}
            {users?.length === 0 && (
              <tr><td colSpan={5} className="px-4 py-8 text-center text-ink-muted">No users yet.</td></tr>
            )}
            {users?.map((u) => (
              <tr key={u.id}>
                <td className="px-4 py-3">
                  <p className="font-medium text-ink">{u.display_name || u.username}</p>
                  <p className="text-xs text-ink-muted">{u.username}{u.id === me.id ? " (you)" : ""}</p>
                </td>
                <td className="px-4 py-3">{ROLE_LABELS[u.role]}</td>
                <td className="space-x-1 px-4 py-3">
                  {u.is_active ? <StatusBadge tone="ok">Active</StatusBadge> : <StatusBadge tone="neutral">Disabled</StatusBadge>}
                  {u.locked && <StatusBadge tone="danger">Locked</StatusBadge>}
                  {u.must_change_password && <StatusBadge tone="warn">Must change password</StatusBadge>}
                </td>
                <td className="px-4 py-3 text-ink-muted">
                  {u.last_login_at ? new Date(u.last_login_at).toLocaleString() : "Never"}
                </td>
                <td className="space-x-1 whitespace-nowrap px-4 py-3 text-right">
                  {u.locked && <Button variant="secondary" onClick={() => void unlock(u)}>Unlock</Button>}
                  <Button variant="ghost" onClick={() => { setNotice(null); setDialog({ kind: "edit", user: u }); }}>
                    Edit
                  </Button>
                  {u.id !== me.id && (
                    <Button variant="ghost" onClick={() => { setNotice(null); setDialog({ kind: "reset", user: u }); }}>
                      Reset password
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Modal open={dialog?.kind === "create"} title="New user" onClose={() => setDialog(null)}>
        <CreateUserForm onDone={(u) => finish(`${u.username} created. They must choose their own password at first login.`)}
                        onCancel={() => setDialog(null)} />
      </Modal>
      <Modal open={dialog?.kind === "edit"} title="Edit user" onClose={() => setDialog(null)}>
        {dialog?.kind === "edit" && (
          <EditUserForm user={dialog.user} isSelf={dialog.user.id === me.id}
                        onDone={(u) => finish(`${u.username} updated.`)} onCancel={() => setDialog(null)} />
        )}
      </Modal>
      <Modal open={dialog?.kind === "reset"} title="Reset password" onClose={() => setDialog(null)}>
        {dialog?.kind === "reset" && (
          <ResetPasswordForm user={dialog.user}
                             onDone={() => finish(`Password for ${dialog.user.username} reset. They are signed out and must choose a new password.`)}
                             onCancel={() => setDialog(null)} />
        )}
      </Modal>
    </div>
  );
}

function FormButtons({ submitting, label, onCancel, danger }: {
  submitting: boolean; label: string; onCancel: () => void; danger?: boolean;
}) {
  return (
    <div className="flex justify-end gap-2 pt-2">
      <Button type="button" variant="secondary" onClick={onCancel}>Cancel</Button>
      <Button type="submit" variant={danger ? "danger" : "primary"} loading={submitting}>{label}</Button>
    </div>
  );
}

export function CreateUserForm({ onDone, onCancel }: { onDone: (u: User) => void; onCancel: () => void }) {
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [role, setRole] = useState<Role>("GUARD");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      onDone(await createUser({ username: username.trim(), display_name: displayName.trim(), role, password }));
    } catch (e) {
      setError(e instanceof ApiError && e.code === "validation_error"
        ? "Check the fields: username 3–32 characters (letters, digits, . _ -) and a name are required."
        : message(e));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={onSubmit} noValidate className="space-y-4">
      {error && <Alert tone="danger">{error}</Alert>}
      <TextField label="Username" autoComplete="off" value={username} onChange={(e) => setUsername(e.target.value)}
                 hint="3–32 characters: letters, digits, dot, hyphen or underscore." />
      <TextField label="Full name" value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
      <RoleSelect value={role} onChange={setRole} />
      <TextField label="Temporary password" type="password" autoComplete="new-password" value={password}
                 onChange={(e) => setPassword(e.target.value)}
                 hint={`${PASSWORD_HINT} The user must change it at first login.`} />
      <FormButtons submitting={submitting} label="Create user" onCancel={onCancel} />
    </form>
  );
}

export function EditUserForm({ user, isSelf, onDone, onCancel }: {
  user: User; isSelf: boolean; onDone: (u: User) => void; onCancel: () => void;
}) {
  const [displayName, setDisplayName] = useState(user.display_name ?? "");
  const [role, setRole] = useState<Role>(user.role);
  const [active, setActive] = useState(user.is_active);
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const sensitive = role !== user.role || active !== user.is_active;
  const disabling = user.is_active && !active;

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    const changes: Parameters<typeof updateUser>[1] = {};
    if (displayName.trim() !== (user.display_name ?? "")) changes.display_name = displayName.trim();
    if (role !== user.role) changes.role = role;
    if (active !== user.is_active) changes.is_active = active;
    if (Object.keys(changes).length === 0) return onCancel();
    if (sensitive) {
      if (!confirmPassword) return setError("Enter your own password to confirm this change.");
      changes.confirm_password = confirmPassword;
    }
    setSubmitting(true);
    try {
      onDone(await updateUser(user.id, changes));
    } catch (e) {
      setError(message(e));
      setConfirmPassword("");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={onSubmit} noValidate className="space-y-4">
      {error && <Alert tone="danger">{error}</Alert>}
      <p className="text-sm text-ink-muted">Username: <span className="font-medium text-ink">{user.username}</span></p>
      <TextField label="Full name" value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
      <RoleSelect value={role} onChange={setRole} disabled={isSelf} />
      <label className="flex items-center gap-2 text-sm text-ink">
        <input type="checkbox" className="size-4" checked={active} disabled={isSelf}
               onChange={(e) => setActive(e.target.checked)} />
        Account active (can log in)
      </label>
      {isSelf && <p className="text-xs text-ink-muted">You cannot change your own role or disable your own account.</p>}
      {disabling && <Alert tone="warn">Disabling signs {user.username} out everywhere and blocks their login.</Alert>}
      {sensitive && (
        <TextField label="Your password (to confirm)" type="password" autoComplete="current-password"
                   value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} />
      )}
      <FormButtons submitting={submitting} label={disabling ? "Disable account" : "Save changes"} onCancel={onCancel}
                   danger={disabling} />
    </form>
  );
}

export function ResetPasswordForm({ user, onDone, onCancel }: { user: User; onDone: () => void; onCancel: () => void }) {
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    if (!newPassword || !confirmPassword) return setError("Fill in both fields.");
    setSubmitting(true);
    try {
      await resetPassword(user.id, newPassword, confirmPassword);
      onDone();
    } catch (e) {
      setError(message(e));
      setConfirmPassword("");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={onSubmit} noValidate className="space-y-4">
      {error && <Alert tone="danger">{error}</Alert>}
      <p className="text-sm text-ink-muted">
        {user.username} will be signed out, unlocked, and must choose a new password at next login.
      </p>
      <TextField label="New temporary password" type="password" autoComplete="new-password" hint={PASSWORD_HINT}
                 value={newPassword} onChange={(e) => setNewPassword(e.target.value)} />
      <TextField label="Your password (to confirm)" type="password" autoComplete="current-password"
                 value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} />
      <FormButtons submitting={submitting} label="Reset password" onCancel={onCancel} danger />
    </form>
  );
}
