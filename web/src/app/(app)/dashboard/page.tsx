import type { Metadata } from "next";

import { DashboardStatus } from "./DashboardStatus";

export const metadata: Metadata = { title: "Dashboard" };

export default function DashboardPage() {
  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-ink">Dashboard</h1>
        <p className="mt-1 text-sm text-ink-muted">
          Visitor statistics appear here once check-in is available.
        </p>
      </div>
      <DashboardStatus />
    </div>
  );
}
