import { Skeleton } from "./Skeleton";

type Tone = "neutral" | "brand" | "ok" | "warn";

const ICON_TONES: Record<Tone, string> = {
  neutral: "bg-surface-subtle text-ink-muted",
  brand: "bg-brand-50 text-brand-700",
  ok: "bg-ok-bg text-ok",
  warn: "bg-warn-bg text-warn",
};

/** One headline number (a KPI). `value` null while loading; "—" when it could not be loaded. */
export function StatTile({ label, value, hint, icon, tone = "neutral", testId }: {
  label: string;
  value: React.ReactNode | null;
  hint?: string;
  icon: React.ReactNode;
  tone?: Tone;
  testId?: string;
}) {
  return (
    <div className="flex min-w-0 flex-col gap-3 rounded-2xl border border-border bg-surface p-4 shadow-card sm:p-5">
      <div className="flex items-center justify-between gap-3">
        <p className="min-w-0 text-sm font-medium text-ink-muted">{label}</p>
        <span aria-hidden="true" className={`flex size-9 shrink-0 items-center justify-center rounded-xl [&_svg]:size-5 ${ICON_TONES[tone]}`}>
          {icon}
        </span>
      </div>
      {value === null
        ? <Skeleton className="h-9 w-16" />
        : <p className="text-3xl leading-9 font-bold tracking-tight text-ink tabular-nums" data-testid={testId}>{value}</p>}
      {hint && <p className="text-xs text-ink-muted">{hint}</p>}
    </div>
  );
}
