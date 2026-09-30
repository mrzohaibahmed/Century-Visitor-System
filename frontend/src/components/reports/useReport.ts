import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "@/lib/api/client";
import type { Keyset } from "@/lib/api/reports";

function asApiError(e: unknown): ApiError {
  return e instanceof ApiError ? e : new ApiError(0, "unknown", "Something went wrong. Please try again.");
}

/**
 * One report request per `key` (the report's range and filters, serialised): a new key cancels the
 * previous request, so an older answer never replaces a newer one. The previous data stays on screen
 * (marked as updating) until the new answer arrives. `key` null: nothing is requested.
 */
export function useReport<T>(key: string | null, load: (signal: AbortSignal) => Promise<T>) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const loader = useRef(load);
  useEffect(() => { loader.current = load; });

  useEffect(() => {
    if (key === null) return;
    const controller = new AbortController();
    // eslint-disable-next-line react-hooks/set-state-in-effect -- data fetch for this key
    setLoading(true);
    setError(null);
    loader.current(controller.signal)
      .then((result) => { if (!controller.signal.aborted) { setData(result); setLoading(false); } })
      .catch((e) => { if (!controller.signal.aborted) { setError(asApiError(e)); setLoading(false); } });
    return () => controller.abort();
  }, [key, attempt]);

  return { data, error, loading, reload: useCallback(() => setAttempt((n) => n + 1), []) };
}

/**
 * A keyset-paged report: the first page (with its totals and range) for each `key`, then "load more"
 * along the server's cursor. There are no page numbers: the API only goes forward.
 */
export function useKeysetReport<R, P extends Keyset<R>>(
  key: string | null, fetchPage: (cursor: string | null, signal: AbortSignal) => Promise<P>,
) {
  const [first, setFirst] = useState<P | null>(null);
  const [items, setItems] = useState<R[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [attempt, setAttempt] = useState(0);
  const fetcher = useRef(fetchPage);
  useEffect(() => { fetcher.current = fetchPage; });
  const current = useRef<AbortController | null>(null);

  const run = useCallback((from: string | null, append: boolean) => {
    current.current?.abort();
    const controller = new AbortController();
    current.current = controller;
    setLoading(true);
    setError(null);
    fetcher.current(from, controller.signal)
      .then((page) => {
        if (controller.signal.aborted) return;
        if (!append) setFirst(page);
        setItems((prev) => (append ? [...prev, ...page.items] : page.items));
        setCursor(page.next_cursor);
        setLoading(false);
      })
      .catch((e) => { if (!controller.signal.aborted) { setError(asApiError(e)); setLoading(false); } });
  }, []);

  useEffect(() => {
    if (key === null) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- a new key starts from the first page
    run(null, false);
    return () => current.current?.abort();
  }, [key, attempt, run]);

  return {
    first, items, loading, error,
    hasMore: cursor !== null,
    loadMore: () => { if (cursor && !loading) run(cursor, true); },
    reload: () => setAttempt((n) => n + 1),
  };
}
