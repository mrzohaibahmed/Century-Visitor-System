import type { Metadata } from "next";
import { notFound } from "next/navigation";

import type { DirectoryKind } from "@/lib/api/directory";

import { DirectoryManager } from "../DirectoryManager";

const PAGES: Record<DirectoryKind, { title: string; description: string }> = {
  hosts: { title: "Hosts", description: "People visitors come to see. Guards pick from this list at check-in." },
  departments: { title: "Departments", description: "Departments visitors can be recorded against." },
  gates: { title: "Gates", description: "Entry points. Each guard session records the gate it works at." },
};

function isKind(value: string): value is DirectoryKind {
  return Object.hasOwn(PAGES, value);
}

export async function generateMetadata({ params }: PageProps<"/directory/[kind]">): Promise<Metadata> {
  const { kind } = await params;
  return { title: isKind(kind) ? PAGES[kind].title : "Not found" };
}

export default async function DirectoryPage({ params }: PageProps<"/directory/[kind]">) {
  const { kind } = await params;
  if (!isKind(kind)) notFound();
  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-ink">{PAGES[kind].title}</h1>
        <p className="mt-1 text-sm text-ink-muted">{PAGES[kind].description}</p>
      </div>
      <DirectoryManager kind={kind} />
    </div>
  );
}
