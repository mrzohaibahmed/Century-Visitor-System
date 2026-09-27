import { useCallback, useEffect, useRef, useState } from "react";

import { errorMessage } from "@/lib/api/client";
import type { Page } from "@/lib/api/visits";

/**
 * Keyset pagination: `fetchPage(cursor)` returns one page; "load more" appends
 * the next. Changing `key` (e.g. the filters) starts again from the first page.
 * Responses for an outdated key are ignored.
 */
export function usePagedList<T>(key: string | null, fetchPage: (cursor: string | null) => Promise<Page<T>>) {
  const [items, setItems] = useState<T[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const generation = useRef(0);
  const fetcher = useRef(fetchPage);
  // Declared before the loading effect so the latest fetcher is in place when it runs.
  useEffect(() => { fetcher.current = fetchPage; });

  const load = useCallback(async (from: string | null, append: boolean) => {
    const mine = ++generation.current;
    setLoading(true);
    setError(null);
    try {
      const page = await fetcher.current(from);
      if (mine !== generation.current) return;
      setItems((prev) => (append ? [...prev, ...page.items] : page.items));
      setCursor(page.next_cursor);
    } catch (e) {
      if (mine === generation.current) setError(errorMessage(e));
    } finally {
      if (mine === generation.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    // A new key starts from the first page; results are applied from the async callback.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setItems([]);
    setCursor(null);
    if (key !== null) void load(null, false);
  }, [key, load]);

  return {
    items,
    loading,
    error,
    hasMore: cursor !== null,
    loadMore: () => { if (cursor) void load(cursor, true); },
    reload: () => { if (key !== null) void load(null, false); },
  };
}
