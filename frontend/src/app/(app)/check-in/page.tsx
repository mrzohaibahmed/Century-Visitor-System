import type { Metadata } from "next";

import { PageHeader } from "@/components/ui/PageHeader";

import { CheckInWizard } from "./CheckInWizard";

export const metadata: Metadata = { title: "Check in" };

export default function CheckInPage() {
  return (
    <div className="mx-auto max-w-2xl space-y-8">
      <PageHeader title="Check in a visitor" description="Every check-in is screened against the watchlist and logged." />
      <CheckInWizard />
    </div>
  );
}
