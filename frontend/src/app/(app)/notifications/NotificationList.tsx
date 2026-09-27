"use client";

import { useState } from "react";

import { NotificationItem } from "@/components/notifications/NotificationItem";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { usePagedList } from "@/hooks/usePagedList";
import { errorMessage } from "@/lib/api/client";
import {
  type AppNotification,
  listNotifications,
  markAllNotificationsRead,
  markNotificationRead,
} from "@/lib/api/notifications";

/** All of the signed-in user's notifications, newest first. */
export function NotificationList() {
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [readIds, setReadIds] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [markingAll, setMarkingAll] = useState(false);
  const list = usePagedList(unreadOnly ? "unread" : "all",
                            (cursor) => listNotifications({ cursor, unreadOnly }));

  async function read(n: AppNotification) {
    try {
      await markNotificationRead(n.id);
      setReadIds((ids) => new Set(ids).add(n.id));
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  async function readAll() {
    setMarkingAll(true);
    setError(null);
    try {
      await markAllNotificationsRead();
      setReadIds(new Set());
      list.reload();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setMarkingAll(false);
    }
  }

  const items = list.items.map((n) => (readIds.has(n.id) ? { ...n, read: true } : n));
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-4">
        <label className="flex items-center gap-2 text-sm text-ink">
          <input type="checkbox" className="size-4" checked={unreadOnly} onChange={(e) => setUnreadOnly(e.target.checked)} />
          Unread only
        </label>
        <Button variant="secondary" onClick={() => void readAll()} loading={markingAll}>Mark all as read</Button>
      </div>
      {(error || list.error) && <Alert tone="danger">{error || list.error}</Alert>}
      <div className="divide-y divide-border overflow-hidden rounded-xl border border-border bg-surface shadow-sm">
        {list.loading && items.length === 0 && <p className="px-4 py-8 text-center text-sm text-ink-muted">Loading…</p>}
        {!list.loading && items.length === 0 && !list.error && (
          <p className="px-4 py-8 text-center text-sm text-ink-muted">No notifications.</p>
        )}
        {items.map((n) => <NotificationItem key={n.id} notification={n} onRead={(x) => void read(x)} />)}
      </div>
      {list.hasMore && (
        <div className="flex justify-center">
          <Button variant="secondary" onClick={list.loadMore} loading={list.loading}>Load more</Button>
        </div>
      )}
    </div>
  );
}
