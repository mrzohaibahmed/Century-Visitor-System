import type { Metadata } from "next";

import { CheckInWizard } from "./CheckInWizard";

export const metadata: Metadata = { title: "Check in" };

export default function CheckInPage() {
  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-ink">Check in a visitor</h1>
        <p className="mt-1 text-sm text-ink-muted">Every check-in is screened against the watchlist and logged.</p>
      </div>
      <CheckInWizard />
    </div>
  );
}
