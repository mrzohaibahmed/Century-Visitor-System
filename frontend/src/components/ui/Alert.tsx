type Tone = "danger" | "warn" | "ok" | "info";

const TONES: Record<Tone, string> = {
  danger: "border-danger/30 bg-danger-bg text-danger",
  warn: "border-warn/30 bg-warn-bg text-warn",
  ok: "border-ok/30 bg-ok-bg text-ok",
  info: "border-brand-100 bg-brand-50 text-brand-700",
};

export function Alert({ tone = "info", children }: { tone?: Tone; children: React.ReactNode }) {
  return (
    <div role={tone === "danger" ? "alert" : "status"} className={`rounded-lg border px-4 py-3 text-sm ${TONES[tone]}`}>
      {children}
    </div>
  );
}
