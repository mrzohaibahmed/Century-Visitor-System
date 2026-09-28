"use client";

import { ChevronRight, Search, SearchX } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Avatar } from "@/components/ui/Avatar";
import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Skeleton";
import { TextField } from "@/components/ui/TextField";
import { usePagedList } from "@/hooks/usePagedList";
import { IDENTITY_LABELS, searchVisitors, type Visitor } from "@/lib/api/visitors";
import { formatDateTime } from "@/lib/format";

/** The search needs a query (the API has no "all visitors" list); results come a page at a time. */
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

  const searching = list.loading && list.items.length === 0;
  return (
    <div className="space-y-6">
      <form onSubmit={onSubmit} role="search"
            className="grid gap-3 rounded-2xl border border-border bg-surface p-5 shadow-card sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start sm:p-6">
        <TextField label="Search visitors" value={text} onChange={(e) => setText(e.target.value)} size="lg"
                   placeholder="Name, CNIC / passport number or phone" autoFocus autoComplete="off" spellCheck={false}
                   error={hint ?? undefined} hint="ID numbers and phones must be complete; names match from the start." />
        {/* Aligned with the input: the label above it is 1.625rem (20px line + 6px gap). */}
        <Button type="submit" size="lg" loading={list.loading} className="sm:mt-[1.625rem]">
          {!list.loading && <Search aria-hidden="true" />}
          Search
        </Button>
      </form>

      {query === null && (
        <div className="flex flex-col items-center gap-2 rounded-2xl border border-dashed border-border px-6 py-12 text-center">
          <span aria-hidden="true" className="flex size-12 items-center justify-center rounded-full bg-surface-subtle text-ink-muted">
            <Search className="size-6" />
          </span>
          <p className="font-semibold text-ink">Search for a visitor</p>
          <p className="max-w-sm text-sm text-ink-muted">Type a name, a CNIC or passport number, or a phone number, then press Search.</p>
        </div>
      )}

      {list.error && (
        <Alert tone="danger" title={list.items.length ? "Could not load more visitors" : "Unable to search visitors"}>
          <p>{list.error}</p>
          <button type="button" onClick={list.reload} className="mt-1 font-semibold underline underline-offset-2">Try again</button>
        </Alert>
      )}

      {query !== null && (searching || list.items.length > 0 || !list.error) && (
        <section aria-label="Search results" aria-busy={searching || undefined}
                 className="rounded-2xl border border-border bg-surface shadow-card">
          {searching && (
            <div role="status" className="space-y-4 p-5 sm:p-6">
              <span className="sr-only">Searching…</span>
              {[0, 1, 2].map((i) => (
                <div key={i} className="flex items-center gap-3">
                  <Skeleton className="size-9 rounded-full" />
                  <Skeleton className="h-4 flex-1" />
                  <Skeleton className="hidden h-4 w-32 md:block" />
                </div>
              ))}
            </div>
          )}

          {!list.loading && !list.error && list.items.length === 0 && (
            <div className="flex flex-col items-center gap-2 px-6 py-12 text-center">
              <span aria-hidden="true" className="flex size-12 items-center justify-center rounded-full bg-surface-subtle text-ink-muted">
                <SearchX className="size-6" />
              </span>
              <p className="font-semibold text-ink">No visitor matches “{query}”.</p>
              <p className="max-w-sm text-sm text-ink-muted">Names match from the start; ID and phone numbers must be complete.</p>
            </div>
          )}

          {list.items.length > 0 && (
            <>
              <p className="border-b border-border px-5 py-3 text-sm text-ink-muted sm:px-6" aria-live="polite">
                {list.hasMore ? `Showing the first ${list.items.length} matches` : `${list.items.length} ${list.items.length === 1 ? "match" : "matches"}`}
                {" "}for “{query}”
              </p>
              {/* One markup for every width: columns from md, cards below. The header only labels the columns visually. */}
              <div aria-hidden="true" className="hidden gap-4 border-b border-border px-6 py-2.5 text-xs font-medium text-ink-muted
                md:grid md:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_minmax(0,0.8fr)_1.25rem]">
                <span>Visitor</span><span>ID</span><span>Phone</span><span />
              </div>
              <ul className="divide-y divide-border">
                {list.items.map((v) => <VisitorRow key={v.id} visitor={v} />)}
              </ul>
            </>
          )}
        </section>
      )}

      {list.hasMore && (
        <div className="flex justify-center">
          <Button variant="secondary" size="lg" onClick={list.loadMore} loading={list.loading}>Load more</Button>
        </div>
      )}
    </div>
  );
}

function VisitorRow({ visitor: v }: { visitor: Visitor }) {
  return (
    <li>
      <Link href={`/visitors/${v.id}`}
            className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 px-5 py-4 transition-colors
              hover:bg-surface-subtle focus-visible:outline-offset-[-3px] sm:px-6
              md:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_minmax(0,0.8fr)_1.25rem] md:gap-4">
        <span className="col-span-2 flex min-w-0 items-center gap-3 md:col-span-1">
          <Avatar name={v.full_name} size="sm" />
          <span className="min-w-0">
            <span className="block truncate font-semibold text-ink">{v.full_name}</span>
            <span className="block text-xs text-ink-muted">Registered {formatDateTime(v.created_at)}</span>
          </span>
        </span>
        <ChevronRight aria-hidden="true" className="col-start-3 row-start-1 size-5 text-ink-subtle md:col-start-4" />
        <span className="col-span-3 min-w-0 pl-12 text-sm md:col-span-1 md:pl-0">
          {v.identity
            ? <><span className="text-ink-muted">{IDENTITY_LABELS[v.identity.type]} </span><span className="font-mono break-all text-ink">{v.identity.number}</span></>
            : <span className="text-ink-muted">No ID</span>}
        </span>
        {/* No inside/not-inside status here: search results do not include the visitor's current
            visit (only the record does), so any status shown would be a guess. */}
        <span className="col-span-3 min-w-0 pl-12 text-sm text-ink md:col-span-1 md:truncate md:pl-0">
          {v.phone ?? <span className="text-ink-muted md:hidden">No phone</span>}
        </span>
      </Link>
    </li>
  );
}
