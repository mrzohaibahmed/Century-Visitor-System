export default function Loading() {
  return (
    <div role="status" aria-live="polite" className="mx-auto max-w-4xl space-y-4">
      <span className="sr-only">Loading…</span>
      <div className="h-8 w-48 animate-pulse rounded bg-border" />
      <div className="h-40 animate-pulse rounded-xl bg-border" />
    </div>
  );
}
