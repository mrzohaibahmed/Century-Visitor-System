"use client";

import { useEffect, useRef, useState } from "react";

import { Avatar } from "@/components/ui/Avatar";
import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Skeleton";
import { TextField } from "@/components/ui/TextField";
import { errorMessage } from "@/lib/api/client";
import { type Host, listHosts } from "@/lib/api/directory";

const SHOWN = 8;

/** Type-ahead over the host directory (searched on the server, so it scales to large directories). */
export function HostPicker({ value, onChange, error }: {
  value: Host | null;
  onChange: (host: Host | null) => void;
  error?: string;
}) {
  const [q, setQ] = useState("");
  const [matches, setMatches] = useState<Host[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  // The button that was used (a match, or Change) disappears with the view: keep focus in the picker.
  const container = useRef<HTMLDivElement>(null);
  const moveFocus = useRef(false);

  useEffect(() => {
    if (value) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      listHosts({ q }, controller.signal)
        .then((hosts) => { setMatches(hosts); setLoadError(null); })
        .catch((e) => { if (!controller.signal.aborted) setLoadError(errorMessage(e)); });
    }, q ? 250 : 0);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [q, value, attempt]);

  useEffect(() => {
    if (!moveFocus.current) return;
    moveFocus.current = false;
    container.current?.querySelector<HTMLElement>(value ? "button" : "input")?.focus();
  }, [value]);

  function choose(host: Host | null) {
    moveFocus.current = true;
    onChange(host);
  }

  if (value) {
    return (
      <div ref={container}>
        <p className="mb-1.5 text-sm font-medium text-ink">Host (person being visited)</p>
        <div className="flex min-h-14 items-center gap-3 rounded-xl border border-brand-200 bg-brand-50/60 py-2 pl-3 pr-2">
          <Avatar name={value.name} size="sm" />
          <div className="min-w-0 flex-1">
            <p className="caps truncate font-semibold text-ink" data-testid="selected-host">{value.name}</p>
            {value.department_name && <p className="caps truncate text-sm text-ink-muted">{value.department_name}</p>}
          </div>
          <Button type="button" variant="ghost" onClick={() => choose(null)}>Change</Button>
        </div>
      </div>
    );
  }

  const shown = matches?.slice(0, SHOWN) ?? [];
  return (
    <div ref={container}>
      <TextField label="Host (person being visited)" value={q} onChange={(e) => setQ(e.target.value)} size="lg"
                 placeholder="Start typing a name" autoComplete="off" error={error ?? loadError ?? undefined} />
      {loadError && (
        <Button type="button" variant="secondary" className="mt-2" onClick={() => { setLoadError(null); setAttempt((n) => n + 1); }}>
          Search again
        </Button>
      )}
      {matches === null && !loadError && (
        <div role="status" className="mt-2 space-y-2 rounded-xl border border-border p-3">
          <span className="sr-only">Loading hosts…</span>
          <Skeleton className="h-5 w-2/3" />
          <Skeleton className="h-5 w-1/2" />
        </div>
      )}
      {matches !== null && (
        <ul aria-label="Matching hosts"
            className="mt-2 max-h-72 divide-y divide-border overflow-y-auto rounded-xl border border-border bg-surface">
          {shown.length === 0 && (
            <li className="px-4 py-4 text-sm text-ink-muted">
              <p className="font-medium text-ink">No host matches “{q}”.</p>
              <p className="mt-0.5">If the person is not in the directory, tick “The host is not in the list” below.</p>
            </li>
          )}
          {shown.map((h) => (
            <li key={h.id}>
              <button type="button" onClick={() => choose(h)}
                      className="flex min-h-14 w-full items-center gap-3 px-4 py-2 text-left transition-colors hover:bg-surface-subtle
                        focus-visible:outline-offset-[-3px]">
                <Avatar name={h.name} size="sm" />
                {/* Stacked, so a long department never squeezes the name out on a phone. */}
                <span className="caps min-w-0 flex-1">
                  <span className="block truncate font-medium text-ink">{h.name}</span>
                  {h.department_name && <span className="block truncate text-sm text-ink-muted">{h.department_name}</span>}
                </span>
              </button>
            </li>
          ))}
          {matches.length > SHOWN && (
            <li className="px-4 py-3 text-sm text-ink-muted">Keep typing to narrow down {matches.length} matches.</li>
          )}
        </ul>
      )}
    </div>
  );
}
