import { type AppNotification, EMAIL_STATUS_TEXT, timeAgo } from "@/lib/api/notifications";

/** One notification: unread ones are highlighted and marked read when clicked. */
export function NotificationItem({ notification: n, onRead }: {
  notification: AppNotification;
  onRead: (n: AppNotification) => void;
}) {
  const where = [n.arrival.gate_name, n.arrival.department_name].filter(Boolean).join(" · ");
  const email = EMAIL_STATUS_TEXT[n.email_status];
  return (
    <button type="button" onClick={() => { if (!n.read) onRead(n); }} data-testid="notification-item"
            aria-label={`${n.read ? "" : "Unread: "}${n.title}. ${n.message}`}
            className={`block w-full px-4 py-3 text-left text-sm ${n.read ? "bg-surface" : "bg-brand-50 hover:bg-brand-100"}`}>
      <span className="flex items-start gap-2">
        <span aria-hidden="true" className={`mt-1.5 size-2 shrink-0 rounded-full ${n.read ? "bg-transparent" : "bg-brand-600"}`} />
        <span className="min-w-0 flex-1">
          <span className="block font-semibold text-ink">{n.title}</span>
          <span className="block text-ink">
            <span className="caps">{n.arrival.visitor_name}</span> has arrived to visit{" "}
            {n.arrival.host_name ? <span className="caps">{n.arrival.host_name}</span> : "you"}.
          </span>
          <span className="mt-0.5 block text-xs text-ink-muted">
            {where && <span className="caps">{where} · </span>}{timeAgo(n.created_at)}{email && ` · ${email}`}
          </span>
        </span>
      </span>
    </button>
  );
}
