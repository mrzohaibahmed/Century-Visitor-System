import type { Metadata } from "next";

import { VisitorSearch } from "./VisitorSearch";

export const metadata: Metadata = { title: "Visitors" };

export default function VisitorsPage() {
  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-ink">Visitors</h1>
        <p className="mt-1 text-sm text-ink-muted">Find a registered visitor. Opening a visitor&apos;s record is logged.</p>
      </div>
      <VisitorSearch />
    </div>
  );
}
