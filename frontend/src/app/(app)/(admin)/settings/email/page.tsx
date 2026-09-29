import type { Metadata } from "next";

import { EmailSettingsManager } from "./EmailSettingsManager";

export const metadata: Metadata = { title: "Email settings" };

export default function EmailSettingsPage() {
  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-ink">Email settings</h1>
        <p className="mt-1 text-sm text-ink-muted">
          The SMTP server Century Gate VMS uses to send e-mail notifications to hosts. The password is stored
          encrypted on the server and is never shown.
        </p>
      </div>
      <EmailSettingsManager />
    </div>
  );
}
