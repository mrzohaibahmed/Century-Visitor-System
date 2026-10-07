import { apiRequest } from "./client";

/** Mirrors app/schemas/notifications.py. The server only ever returns the signed-in user's own. */
export type EmailStatus = "NONE" | "PENDING" | "SENDING" | "SENT" | "FAILED";

export type NotificationType =
  | "HOST_VISITOR_ARRIVAL"
  | "DEPARTMENT_VISITOR_ARRIVAL"
  | "HOST_VISITOR_OVERSTAY"
  | "DEPARTMENT_VISITOR_OVERSTAY";

export type AppNotification = {
  id: string;
  type: NotificationType;
  title: string;
  message: string;
  created_at: string;
  read: boolean;
  read_at: string | null;
  arrival: {
    visitor_name: string;
    host_name: string | null;
    gate_name: string | null;
    department_name: string | null;
    check_in_at: string;
  };
  email_status: EmailStatus;
};

export type NotificationPage = { items: AppNotification[]; next_cursor: string | null; unread_count: number };

export function listNotifications(options: { cursor?: string | null; unreadOnly?: boolean } = {},
                                  signal?: AbortSignal): Promise<NotificationPage> {
  const params = new URLSearchParams();
  if (options.unreadOnly) params.set("unread_only", "true");
  if (options.cursor) params.set("cursor", options.cursor);
  const text = params.toString();
  return apiRequest<NotificationPage>(`/notifications${text ? `?${text}` : ""}`, { signal });
}

/** Idempotent: marking an already-read notification changes nothing. */
export function markNotificationRead(id: string): Promise<AppNotification> {
  return apiRequest<AppNotification>(`/notifications/${encodeURIComponent(id)}/read`, { method: "POST" });
}

export function markAllNotificationsRead(): Promise<{ marked: number; unread_count: number }> {
  return apiRequest<{ marked: number; unread_count: number }>("/notifications/read-all", { method: "POST" });
}

export const EMAIL_STATUS_TEXT: Record<EmailStatus, string | null> = {
  NONE: null,
  PENDING: "E-mail to the host queued",
  SENDING: "E-mail to the host being sent",
  SENT: "Host e-mailed",
  FAILED: "E-mail to the host failed",
};

/** "just now", "2 minutes ago", "3 hours ago", else the date. */
export function timeAgo(iso: string, now: Date = new Date()): string {
  const minutes = Math.floor((now.getTime() - new Date(iso).getTime()) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? "" : "s"} ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  return new Date(iso).toLocaleDateString(undefined, { dateStyle: "medium" });
}
