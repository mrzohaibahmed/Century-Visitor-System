import { useCallback, useEffect, useRef, useState } from "react";

import { errorMessage } from "@/lib/api/client";
import { activeVisits, listVisits, type Visit } from "@/lib/api/visits";
import { isoDay } from "@/lib/format";

export const REFRESH_MS = 60_000;
export const LONG_STAY_HOURS = 8;
/** Today's visits are counted in the browser from the visit list (at most this many are fetched). */
export const TODAY_CAP = 500;
const PAGE_SIZE = 100;

export type Loadable<T> = { data: T | null; error: string | null };
export type Today = { items: Visit[]; capped: boolean };

/** All of today's check-ins (the API's date filter is by check-in day, in the site's time zone), newest first. */
async function loadToday(signal: AbortSignal): Promise<Today> {
  const day = isoDay();
  const items: Visit[] = [];
  let cursor: string | null = null;
  do {
    const page = await listVisits({ from: day, to: day }, cursor, signal, PAGE_SIZE);
    items.push(...page.items);
    cursor = page.next_cursor;
  } while (cursor && items.length < TODAY_CAP);
  return { items: items.slice(0, TODAY_CAP), capped: cursor !== null || items.length > TODAY_CAP };
}

/**
 * The dashboard's data, refreshed every minute: who is inside now (exact, from /visits/active)
 * and today's check-ins. A failure keeps the last good data and reports the error.
 */
export function useDashboardData() {
  const [inside, setInside] = useState<Loadable<{ items: Visit[]; total: number }>>({ data: null, error: null });
  const [today, setToday] = useState<Loadable<Today>>({ data: null, error: null });
  const [loadedAt, setLoadedAt] = useState<number | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const controller = useRef<AbortController | null>(null);

  const load = useCallback(async () => {
    controller.current?.abort();
    const current = new AbortController();
    controller.current = current;
    setRefreshing(true);
    const [a, t] = await Promise.allSettled([activeVisits(current.signal), loadToday(current.signal)]);
    if (current.signal.aborted) return;
    setInside((prev) => a.status === "fulfilled" ? { data: a.value, error: null } : { ...prev, error: errorMessage(a.reason) });
    setToday((prev) => t.status === "fulfilled" ? { data: t.value, error: null } : { ...prev, error: errorMessage(t.reason) });
    // "Updated at" only means something when fresh data actually arrived.
    if (a.status === "fulfilled" || t.status === "fulfilled") setLoadedAt(Date.now());
    setRefreshing(false);
  }, []);

  useEffect(() => {
    // First load and periodic refresh: results are applied from the async callback.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
    const timer = setInterval(() => void load(), REFRESH_MS);
    return () => { clearInterval(timer); controller.current?.abort(); };
  }, [load]);

  return { inside, today, loadedAt, refreshing, reload: load };
}

export function isLongStay(visit: Visit, now: number): boolean {
  return visit.status === "CHECKED_IN" && now - new Date(visit.check_in_at).getTime() > LONG_STAY_HOURS * 3600_000;
}
