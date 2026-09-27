"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
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
        <p className="mb-1 text-sm font-medium text-ink">Host (person being visited)</p>
        <div className="flex items-center justify-between gap-3 rounded-lg border border-border bg-canvas px-3 py-2">
          <div>
            <p className="font-semibold text-ink" data-testid="selected-host">{value.name}</p>
            {value.department_name && <p className="text-xs text-ink-muted">{value.department_name}</p>}
          </div>
          <Button type="button" variant="ghost" onClick={() => onChange(null)}>Change</Button>
        </div>
      </div>
    );
  }

  const shown = matches?.slice(0, SHOWN) ?? [];
  return (
    <div>
      <TextField label="Host (person being visited)" value={q} onChange={(e) => setQ(e.target.value)}
                 placeholder="Start typing a name" autoComplete="off" error={error ?? loadError ?? undefined} />
      {matches !== null && (
        <ul aria-label="Matching hosts" className="mt-2 max-h-64 divide-y divide-border overflow-y-auto rounded-lg border border-border">
          {shown.length === 0 && <li className="px-3 py-2 text-sm text-ink-muted">No host matches “{q}”.</li>}
          {shown.map((h) => (
            <li key={h.id}>
              <button type="button" onClick={() => onChange(h)}
                      className="flex w-full items-center justify-between px-3 py-2 text-left text-sm hover:bg-canvas">
                <span className="font-medium text-ink">{h.name}</span>
                <span className="text-xs text-ink-muted">{h.department_name ?? ""}</span>
              </button>
            </li>
          ))}
          {matches.length > SHOWN && (
            <li className="px-3 py-2 text-xs text-ink-muted">Keep typing to narrow down {matches.length} matches.</li>
          )}
        </ul>
      )}
    </div>
  );
}
