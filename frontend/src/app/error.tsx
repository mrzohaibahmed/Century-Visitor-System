"use client";

export default function ErrorPage({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  // Technical details stay in the browser console / server logs, never on screen.
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-3 px-6 text-center">
      <h1 className="text-2xl font-bold text-ink">Something went wrong</h1>
      <p className="max-w-md text-ink-muted">
        An unexpected error occurred. Please try again. If it keeps happening, contact the administrator
        {error.digest ? ` and quote reference ${error.digest}` : ""}.
      </p>
      <button
        type="button"
        onClick={reset}
        className="mt-2 rounded-lg bg-brand-600 px-4 py-2.5 font-medium text-white hover:bg-brand-700"
      >
        Try again
      </button>
    </main>
  );
}
