"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Card } from "@/components/ui/Card";
import { errorMessage } from "@/lib/api/client";
import { activeVisits, type Visit } from "@/lib/api/visits";
import { formatDuration } from "@/lib/format";

const REFRESH_MS = 60_000;
const LONG_STAY_HOURS = 8;

/** Who is inside right now, plus the quick actions a guard needs most. */
export function InsideSummary() {
  const [data, setData] = useState<{ items: Visit[]; total: number; loadedAt: number } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = () => activeVisits()
      .then((d) => { if (!cancelled) { setData({ ...d, loadedAt: Date.now() }); setError(null); } })
      .catch((e) => { if (!cancelled) setError(errorMessage(e)); });
    void load();
    const timer = setInterval(load, REFRESH_MS);
    return () => { cancelled = true; clearInterval(timer); };
  }, []);

  const longStays = data?.items.filter(
    (v) => data.loadedAt - new Date(v.check_in_at).getTime() > LONG_STAY_HOURS * 3600_000) ?? [];
  const actionClass = "inline-flex min-h-10 items-center rounded-lg px-4 text-sm font-semibold";

  return (
    <Card title="On the premises" actions={
      <div className="flex gap-2">
        <Link href="/check-in" className={`${actionClass} bg-brand-600 text-white hover:bg-brand-700`}>Check in</Link>
        <Link href="/check-out" className={`${actionClass} border border-border text-ink hover:bg-canvas`}>Check out</Link>
      </div>
    }>
      {error && <p className="text-sm text-danger">{error}</p>}
      {!error && (
        <div className="flex flex-wrap items-end gap-8">
          <div>
            <p className="text-4xl font-bold text-ink" data-testid="inside-count">{data ? data.total : "…"}</p>
            <p className="text-sm text-ink-muted">visitor{data?.total === 1 ? "" : "s"} inside now</p>
          </div>
          {longStays.length > 0 && (
            <div className="text-sm">
              <p className="font-semibold text-warn">Inside longer than {LONG_STAY_HOURS} hours:</p>
              <ul className="text-ink-muted">
                {longStays.slice(0, 5).map((v) => (
                  <li key={v.id}>{v.visitor.name} ({v.visit_number}) · {formatDuration(v.check_in_at)}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}
