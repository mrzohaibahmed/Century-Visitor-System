import type { Metadata } from "next";
import Image from "next/image";
import { redirect } from "next/navigation";

import crest from "@/assets/century-crest.png";
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

/** A thin gold rule with a small diamond in the middle. */
function GoldDivider({ className = "" }: { className?: string }) {
  return (
    <div aria-hidden="true" className={`flex items-center gap-3 ${className}`}>
      <span className="h-px w-16 bg-linear-to-r from-transparent to-gold-400/70" />
      <span className="size-1.5 rotate-45 bg-gold-400" />
      <span className="h-px w-16 bg-linear-to-l from-transparent to-gold-400/70" />
    </div>
  );
}

export default async function LoginPage({ searchParams }: PageProps<"/login">) {
  const params = await searchParams;
  const next = safeNextPath(typeof params.next === "string" ? params.next : null);
  if (await getServerSession()) redirect(next);
  const reason = typeof params.reason === "string" ? REASONS[params.reason] : undefined;

  return (
    <main className="grid min-h-screen bg-canvas lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
      {/* Brand panel: the same navy and gold in both themes. Decorative; the form side carries the text. */}
      <section
        aria-hidden="true"
        className="relative hidden overflow-hidden bg-linear-160 from-brand-900 to-navy-950 lg:flex lg:flex-col lg:items-center lg:justify-center"
      >
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_60%_45%_at_50%_42%,rgb(213_178_58/0.18),transparent)]" />
        <div className="pointer-events-none absolute inset-6 rounded-3xl border border-gold-400/20" />
        <div className="pointer-events-none absolute inset-8 rounded-[1.25rem] border border-gold-400/10" />

        <div className="relative flex flex-col items-center px-12 text-center">
          <Image
            src={crest}
            alt=""
            preload
            sizes="320px"
            className="h-auto w-72 drop-shadow-[0_8px_32px_rgb(213_178_58/0.25)] xl:w-80"
          />
          <p className="mt-10 text-sm font-semibold tracking-[0.45em] text-gold-300">CENTURY GATE</p>
          <GoldDivider className="mt-4" />
          <p className="mt-4 text-lg font-light tracking-wide text-white/80">Visitor Management System</p>
        </div>

        <p className="absolute bottom-12 text-xs tracking-[0.2em] text-white/40">
          AUTHORISED PERSONNEL ONLY
        </p>
      </section>

      {/* Sign-in panel: follows the light/dark theme like the rest of the app. */}
      <section className="flex items-center justify-center px-4 py-12 sm:px-8">
        <div className="w-full max-w-sm">
          <div className="mb-8 flex flex-col items-center lg:hidden">
            <Image src={crest} alt="Century Gate" preload sizes="128px" className="h-auto w-32" />
            <p className="mt-4 text-xs font-semibold tracking-[0.4em] text-ink-muted">CENTURY GATE</p>
          </div>

          <p className="hidden text-xs font-semibold tracking-[0.3em] text-ink-muted lg:block">CENTURY GATE</p>
          <h1 className="mt-2 text-title text-ink max-lg:text-center">Welcome</h1>
          <p className="mt-2 mb-8 text-sm text-ink-muted max-lg:text-center">
            Log in to Visitor Management to continue.
          </p>

          <LoginForm next={next} notice={reason} />

          <div className="mt-10 border-t border-border pt-6 text-center text-xs text-ink-subtle">
            Access is restricted to authorised staff. Every login is recorded.
          </div>
        </div>
      </section>
    </main>
  );
}
