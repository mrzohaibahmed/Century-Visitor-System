import type { Metadata } from "next";

import { PageHeader } from "@/components/ui/PageHeader";

import { VisitorSearch } from "./VisitorSearch";

export const metadata: Metadata = { title: "Visitors" };

export default function VisitorsPage() {
  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <PageHeader title="Visitors" description="Registered visitors are listed alphabetically. Search by name, ID or phone." />
      <VisitorSearch />
    </div>
  );
}
