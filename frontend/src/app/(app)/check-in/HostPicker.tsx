"use client";

import { useEffect, useState } from "react";

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

  useEffect(() => {
    if (value) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      listHosts({ q }, controller.signal)
        .then((hosts) => { setMatches(hosts); setLoadError(null); })
        .catch((e) => { if (!controller.signal.aborted) setLoadError(errorMessage(e)); });
    }, q ? 250 : 0);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [q, value]);

  if (value) {
    return (
      <div>
        <p className="mb-1.5 text-sm font-medium text-ink">Host (person being visited)</p>
        <div className="flex min-h-14 items-center gap-3 rounded-xl border border-brand-200 bg-brand-50/60 py-2 pl-3 pr-2">
          <Avatar name={value.name} size="sm" />
          <div className="min-w-0 flex-1">
            <p className="truncate font-semibold text-ink" data-testid="selected-host">{value.name}</p>
            {value.department_name && <p className="truncate text-sm text-ink-muted">{value.department_name}</p>}
          </div>
          <Button type="button" variant="ghost" onClick={() => onChange(null)}>Change</Button>
        </div>
      </div>
    );
  }

  const shown = matches?.slice(0, SHOWN) ?? [];
  return (
    <div>
      <TextField label="Host (person being visited)" value={q} onChange={(e) => setQ(e.target.value)} size="lg"
                 placeholder="Start typing a name" autoComplete="off" error={error ?? loadError ?? undefined} />
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
              <button type="button" onClick={() => onChange(h)}
                      className="flex min-h-14 w-full items-center gap-3 px-4 py-2 text-left transition-colors hover:bg-surface-subtle
                        focus-visible:outline-offset-[-3px]">
                <Avatar name={h.name} size="sm" />
                <span className="min-w-0 flex-1 truncate font-medium text-ink">{h.name}</span>
                <span className="shrink-0 text-sm text-ink-muted">{h.department_name ?? ""}</span>
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
