import type { Metadata } from "next";

import { NotificationList } from "./NotificationList";

export const metadata: Metadata = { title: "Notifications" };

export default function NotificationsPage() {
  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-ink">Notifications</h1>
        <p className="mt-1 text-sm text-ink-muted">
          Arrivals of visitors for hosts linked to your account. An administrator sets the link on the Hosts page.
        </p>
      </div>
      <NotificationList />
    </div>
  );
}
