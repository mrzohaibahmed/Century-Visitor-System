import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { safeNextPath } from "@/lib/api/auth";
import { getServerSession } from "@/lib/api/server";

import { LoginForm } from "./LoginForm";

export const metadata: Metadata = { title: "Log in" };
export const dynamic = "force-dynamic";

const REASONS: Record<string, string> = {
  expired: "Your session has expired. Please log in again.",
  idle: "You were logged out after a period of inactivity.",
  logged_out: "You have been logged out.",
};

export default async function LoginPage({ searchParams }: PageProps<"/login">) {
  const params = await searchParams;
  const next = safeNextPath(typeof params.next === "string" ? params.next : null);
  if (await getServerSession()) redirect(next);
  const reason = typeof params.reason === "string" ? REASONS[params.reason] : undefined;

  return (
    <main className="flex min-h-screen items-center justify-center bg-brand-900 px-4">
      <div className="w-full max-w-sm rounded-2xl bg-surface p-8 shadow-xl">
        <p className="text-xs font-bold tracking-widest text-brand-600">CENTURY GATE</p>
        <h1 className="mt-1 text-2xl font-bold text-ink">Visitor Management</h1>
        <p className="mt-1 mb-6 text-sm text-ink-muted">Log in to continue.</p>
        <LoginForm next={next} notice={reason} />
      </div>
    </main>
  );
}
