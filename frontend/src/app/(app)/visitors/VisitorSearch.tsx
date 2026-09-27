"use client";

import Link from "next/link";
import { useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { TextField } from "@/components/ui/TextField";
import { usePagedList } from "@/hooks/usePagedList";
import { IDENTITY_LABELS, searchVisitors } from "@/lib/api/visitors";

export function VisitorSearch() {
  const [text, setText] = useState("");
  const [query, setQuery] = useState<string | null>(null);
  const [hint, setHint] = useState<string | null>(null);
  const list = usePagedList(query, (cursor) => searchVisitors(query ?? "", cursor));

  function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    const q = text.trim();
    if (q.length < 2) return setHint("Type at least 2 characters.");
    setHint(null);
    if (q === query) list.reload();
    else setQuery(q);
  }

  return (
    <div className="space-y-4">
      <form onSubmit={onSubmit} className="flex items-start gap-2 rounded-xl border border-border bg-surface p-4 shadow-sm">
        <TextField label="Search visitors" className="flex-1" value={text} onChange={(e) => setText(e.target.value)}
                   placeholder="Name, CNIC / passport number or phone" autoFocus error={hint ?? undefined}
                   hint="ID numbers and phones must be complete; names match from the start." />
        <Button type="submit" className="mt-6" loading={list.loading}>Search</Button>
      </form>

      {list.error && <Alert tone="danger">{list.error}</Alert>}
      {query !== null && (
        <ul className="divide-y divide-border rounded-xl border border-border bg-surface shadow-sm">
          {list.items.length === 0 && (
            <li className="px-4 py-6 text-center text-sm text-ink-muted">
              {list.loading ? "Searching…" : `No visitor matches “${query}”.`}
            </li>
          )}
          {list.items.map((v) => (
            <li key={v.id}>
              <Link href={`/visitors/${v.id}`} className="flex items-center justify-between gap-4 px-4 py-3 hover:bg-canvas">
                <div>
                  <p className="font-medium text-ink">{v.full_name}</p>
                  <p className="text-xs text-ink-muted">
                    {v.identity ? `${IDENTITY_LABELS[v.identity.type]} ${v.identity.number}` : "No ID"}
                    {v.phone && ` · ${v.phone}`}
                  </p>
                </div>
                {v.active_visit && <StatusBadge tone="ok">Inside</StatusBadge>}
              </Link>
            </li>
          ))}
        </ul>
      )}
      {list.hasMore && (
        <div className="flex justify-center">
          <Button variant="secondary" onClick={list.loadMore} loading={list.loading}>Load more</Button>
        </div>
      )}
    </div>
  );
}
