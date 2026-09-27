import type { Metadata } from "next";

import { VisitorDetail } from "./VisitorDetail";

export const metadata: Metadata = { title: "Visitor" };

export default async function VisitorPage({ params }: PageProps<"/visitors/[id]">) {
  const { id } = await params;
  return (
    <div className="mx-auto max-w-5xl">
      <VisitorDetail id={id} />
    </div>
  );
}
