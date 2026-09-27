import type { Metadata } from "next";

import { ChangePasswordForm } from "./ChangePasswordForm";

export const metadata: Metadata = { title: "Change password" };

export default function ChangePasswordPage() {
  return (
    <div className="mx-auto max-w-md space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-ink">Change password</h1>
        <p className="mt-1 text-sm text-ink-muted">Other devices signed in to your account will be signed out.</p>
      </div>
      <ChangePasswordForm />
    </div>
  );
}
