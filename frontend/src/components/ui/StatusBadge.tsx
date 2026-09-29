type Tone = "ok" | "warn" | "danger" | "neutral";

const TONES: Record<Tone, string> = {
  ok: "bg-ok-bg text-ok",
  warn: "bg-warn-bg text-warn",
  danger: "bg-danger-bg text-danger",
  neutral: "bg-canvas text-ink-muted",
};

export function StatusBadge({ tone, children }: { tone: Tone; children: React.ReactNode }) {
  return (
    <span className={`caps inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-sm font-semibold ${TONES[tone]}`}>
      <span aria-hidden="true" className="size-2 rounded-full bg-current" />
      {children}
    </span>
  );
}
