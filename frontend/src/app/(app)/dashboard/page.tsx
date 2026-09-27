import type { Metadata } from "next";

import { DashboardStatus } from "./DashboardStatus";
import { InsideSummary } from "./InsideSummary";

export const metadata: Metadata = { title: "Dashboard" };

export default function DashboardPage() {
  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <h1 className="text-2xl font-bold text-ink">Dashboard</h1>
      <InsideSummary />
      <DashboardStatus />
    </div>
  );
}
