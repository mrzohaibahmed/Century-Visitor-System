import type { Metadata } from "next";

import { PageHeader } from "@/components/ui/PageHeader";

import { CheckOutDesk } from "./CheckOutDesk";

export const metadata: Metadata = { title: "Check out" };

export default function CheckOutPage() {
  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <PageHeader title="Check out visitor"
                  description="Scan the visitor's badge, type the visit number, or choose them from the visitors inside." />
      <CheckOutDesk />
    </div>
  );
}
