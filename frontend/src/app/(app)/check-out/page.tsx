import type { Metadata } from "next";

import { CheckOutDesk } from "./CheckOutDesk";

export const metadata: Metadata = { title: "Check out" };

export default function CheckOutPage() {
  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-ink">Check out</h1>
        <p className="mt-1 text-sm text-ink-muted">Record visitors leaving the premises.</p>
      </div>
      <CheckOutDesk />
    </div>
  );
}
