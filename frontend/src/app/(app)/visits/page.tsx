import type { Metadata } from "next";

import { VisitHistory } from "./VisitHistory";

export const metadata: Metadata = { title: "Visit history" };

export default function VisitsPage() {
  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-ink">Visit history</h1>
        <p className="mt-1 text-sm text-ink-muted">Shows today&apos;s visits by default. Newest first.</p>
      </div>
      <VisitHistory />
    </div>
  );
}
