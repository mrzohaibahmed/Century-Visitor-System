import type { Metadata } from "next";

import { UsersManager } from "./UsersManager";

export const metadata: Metadata = { title: "Users" };

export default function UsersPage() {
  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-ink">Users</h1>
        <p className="mt-1 text-sm text-ink-muted">
          Staff accounts for this system. Accounts are disabled rather than deleted, so their history stays intact.
        </p>
      </div>
      <UsersManager />
    </div>
  );
}
