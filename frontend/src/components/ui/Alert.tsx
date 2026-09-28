import { CircleAlert, CircleCheck, Info, TriangleAlert } from "lucide-react";

type Tone = "danger" | "warn" | "ok" | "info";

const TONES: Record<Tone, { box: string; Icon: typeof Info }> = {
  danger: { box: "border-danger/25 bg-danger-bg text-danger", Icon: CircleAlert },
  warn: { box: "border-warn/25 bg-warn-bg text-warn", Icon: TriangleAlert },
  ok: { box: "border-ok/25 bg-ok-bg text-ok", Icon: CircleCheck },
  info: { box: "border-brand-100 bg-brand-50 text-brand-700", Icon: Info },
};

export function Alert({ tone = "info", title, children }: { tone?: Tone; title?: string; children?: React.ReactNode }) {
  const { box, Icon } = TONES[tone];
  return (
    <div role={tone === "danger" ? "alert" : "status"} className={`flex gap-3 rounded-xl border px-4 py-3 text-sm ${box}`}>
      <Icon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
      <div className="min-w-0 flex-1">
        {title && <p className="font-semibold">{title}</p>}
        {children && <div className={title ? "mt-0.5" : undefined}>{children}</div>}
      </div>
    </div>
  );
}
