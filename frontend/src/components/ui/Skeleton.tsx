/** A placeholder block while content loads. Decorative: announce loading with text elsewhere. */
export function Skeleton({ className = "" }: { className?: string }) {
  return <div aria-hidden="true" className={`animate-pulse rounded-lg bg-border/70 ${className}`} />;
}
