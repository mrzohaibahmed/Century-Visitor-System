import type { Metadata } from "next";

import { WatchlistManager } from "./WatchlistManager";

export const metadata: Metadata = { title: "Watchlist" };

export default function WatchlistPage() {
  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-ink">Watchlist</h1>
        <p className="mt-1 text-sm text-ink-muted">
          People who must not be admitted. Every check-in is screened against the active entries. Entries are
          expired or disabled, never deleted, and every change is logged.
        </p>
      </div>
      <WatchlistManager />
    </div>
  );
}
