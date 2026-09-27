"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/Button";
import { errorMessage } from "@/lib/api/client";
import {
  type AppNotification,
  listNotifications,
  markAllNotificationsRead,
  markNotificationRead,
} from "@/lib/api/notifications";

import { NotificationItem } from "./NotificationItem";

const POLL_MS = 30_000;
const SHOWN = 6;

/**
 * The bell in the top bar: the signed-in user's own notifications (e.g. "your visitor has arrived"
 * for hosts whose "Linked app account" is this user). The unread count always comes from the server.
 * Polls every 30 s while the tab is visible.
 */
export function NotificationBell() {
  const [items, setItems] = useState<AppNotification[] | null>(null);
  const [unread, setUnread] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [markingAll, setMarkingAll] = useState(false);
  const panel = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    try {
      const page = await listNotifications();
      setItems(page.items);
      setUnread(page.unread_count);
      setError(null);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);

  useEffect(() => {
    // First load and polling: results are applied from the async callback.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
    const timer = setInterval(() => { if (document.visibilityState === "visible") void load(); }, POLL_MS);
    return () => clearInterval(timer);
  }, [load]);

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent | KeyboardEvent) => {
      if (event instanceof KeyboardEvent ? event.key === "Escape" : !panel.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", close); };
  }, [open]);

  async function read(n: AppNotification) {
    try {
      const updated = await markNotificationRead(n.id);
      setItems((all) => all?.map((x) => (x.id === n.id ? updated : x)) ?? null);
      setUnread((count) => Math.max(0, count - 1));
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  async function readAll() {
    setMarkingAll(true);
    try {
      await markAllNotificationsRead();
      await load();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setMarkingAll(false);
    }
  }

  const label = unread ? `Notifications, ${unread} unread` : "Notifications";
  return (
    <div className="relative" ref={panel}>
      <button type="button" aria-label={label} aria-expanded={open} aria-haspopup="true"
              onClick={() => { setOpen(!open); if (!open) void load(); }}
              className="relative rounded-lg p-2 text-ink-muted hover:bg-canvas hover:text-ink">
        <svg aria-hidden="true" viewBox="0 0 24 24" className="size-6" fill="none" stroke="currentColor" strokeWidth="1.8"
             strokeLinecap="round" strokeLinejoin="round">
          <path d="M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
          <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
        </svg>
        {unread > 0 && (
          <span data-testid="notification-count"
                className="absolute -right-0.5 -top-0.5 min-w-5 rounded-full bg-danger px-1.5 text-center text-xs font-bold leading-5 text-white">
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </button>

      {open && (
        <div role="dialog" aria-label="Notifications"
             className="absolute right-0 z-20 mt-2 w-96 max-w-[90vw] overflow-hidden rounded-xl border border-border bg-surface shadow-xl">
          <div className="flex items-center justify-between border-b border-border px-4 py-3">
            <h2 className="text-sm font-semibold text-ink">Notifications</h2>
            {unread > 0 && (
              <Button variant="ghost" className="min-h-8 px-2 py-1 text-xs" loading={markingAll} onClick={() => void readAll()}>
                Mark all as read
              </Button>
            )}
          </div>
          <div className="max-h-96 divide-y divide-border overflow-y-auto">
            {error && <p role="alert" className="px-4 py-3 text-sm text-danger">Notifications could not be loaded: {error}</p>}
            {items === null && !error && <p className="px-4 py-6 text-center text-sm text-ink-muted">Loading…</p>}
            {items !== null && items.length === 0 && (
              <p className="px-4 py-6 text-center text-sm text-ink-muted">No notifications yet.</p>
            )}
            {items?.slice(0, SHOWN).map((n) => <NotificationItem key={n.id} notification={n} onRead={(x) => void read(x)} />)}
          </div>
          <div className="border-t border-border px-4 py-2 text-right">
            <Link href="/notifications" onClick={() => setOpen(false)} className="text-sm font-medium text-brand-700 hover:underline">
              View all
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}
