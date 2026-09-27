import { apiRequest } from "./client";
import type { Identity } from "./visitors";
import type { Page, Ref } from "./visits";

/** Mirrors app/schemas/watchlist.py. */
export type WatchlistStatus = "ACTIVE" | "EXPIRED" | "DISABLED";

export type WatchlistEntry = {
  id: string;
  identity: Identity;
  name: string | null;
  reason: string;
  status: WatchlistStatus;
  expires_at: string | null;
  created_at: string;
  created_by: Ref;
  updated_at: string | null;
  disabled_at: string | null;
  disabled_by: Ref | null;
  disabled_reason: string | null;
};

export type WatchlistCreated = WatchlistEntry & { inside_visit_number: string | null };

export type NewWatchlistEntry = { identity: Identity; name?: string | null; reason: string; expires_at?: string | null };
export type WatchlistChanges = { name?: string; reason?: string; expires_at?: string; clear_expiry?: boolean };

export function listWatchlist(filters: { q?: string; status?: WatchlistStatus | "" }, cursor?: string | null,
                              signal?: AbortSignal): Promise<Page<WatchlistEntry>> {
  const params = new URLSearchParams();
  if (filters.q?.trim()) params.set("q", filters.q.trim());
  if (filters.status) params.set("status", filters.status);
  if (cursor) params.set("cursor", cursor);
  const text = params.toString();
  return apiRequest<Page<WatchlistEntry>>(`/watchlist${text ? `?${text}` : ""}`, { signal });
}

export function addWatchlistEntry(entry: NewWatchlistEntry): Promise<WatchlistCreated> {
  return apiRequest<WatchlistCreated>("/watchlist", { method: "POST", body: entry });
}

export function updateWatchlistEntry(id: string, changes: WatchlistChanges): Promise<WatchlistEntry> {
  return apiRequest<WatchlistEntry>(`/watchlist/${encodeURIComponent(id)}`, { method: "PATCH", body: changes });
}

export function expireWatchlistEntry(id: string): Promise<WatchlistEntry> {
  return apiRequest<WatchlistEntry>(`/watchlist/${encodeURIComponent(id)}/expire`, { method: "POST" });
}

export function disableWatchlistEntry(id: string, note: string): Promise<WatchlistEntry> {
  return apiRequest<WatchlistEntry>(`/watchlist/${encodeURIComponent(id)}/disable`, { method: "POST", body: { note } });
}

/**
 * <input type="date"> value → the end of that day in the browser's time zone, as an ISO instant.
 * "Banned until 30 June" means until the end of 30 June at the gate.
 */
export function endOfDayIso(day: string): string {
  const [y, m, d] = day.split("-").map(Number);
  return new Date(y, m - 1, d, 23, 59, 59).toISOString();
}
