"use client";

import { FileDown, Inbox, RefreshCw, SlidersHorizontal } from "lucide-react";
import { useEffect, useId, useState } from "react";
import { toast } from "sonner";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Skeleton";
import { TextField } from "@/components/ui/TextField";
import { ApiError } from "@/lib/api/client";
import { downloadReportCsv, type ExportReport, type RangeChoice, type ReportRange } from "@/lib/api/reports";

// ------------------------------------------------------------------------------------------ errors
/** A message that is safe to show: never a raw exception. The API's own messages are written for users. */
export function reportErrorMessage(error: ApiError): string {
  if (error.status === 403) return "You do not have permission to view reports.";
  if (error.status === 0) return "Cannot reach the server. Check the network connection and try again.";
  if (error.status >= 500) return "The report could not be loaded. Please try again in a moment.";
  return error.message;                                   // 422 (e.g. the date range), 429
}

export function ReportError({ error, onRetry }: { error: ApiError; onRetry: () => void }) {
  const retry = error.status !== 403 && error.status !== 422;
  return (
    <Alert tone="danger" title="This report could not be loaded">
      <p>{reportErrorMessage(error)}</p>
      {retry && (
        <Button variant="secondary" size="sm" className="mt-3" onClick={onRetry}>
          <RefreshCw aria-hidden="true" /> Try again
        </Button>
      )}
    </Alert>
  );
}

// ------------------------------------------------------------------------------------------ period
/** "30 Sep 2026" from YYYY-MM-DD, without any time-zone arithmetic in the browser. */
export function formatDay(day: string, withYear = true): string {
  const [y, m, d] = day.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString(undefined, {
    day: "numeric", month: "short", ...(withYear ? { year: "numeric" } : {}), timeZone: "UTC",
  });
}

export function periodText(range: ReportRange): string {
  const days = range.from === range.to ? formatDay(range.from) : `${formatDay(range.from)} – ${formatDay(range.to)}`;
  return `${days} (${range.timezone})`;
}

// ------------------------------------------------------------------------------------------ tables
export type Column<T> = {
  key: string;
  header: string;
  cell: (row: T) => React.ReactNode;
  numeric?: boolean;
  className?: string;
};

/** A report table: headers, horizontal scrolling on narrow screens, loading and empty states. */
export function DataTable<T>({ caption, columns, rows, rowKey, loading, empty }: {
  caption: string;
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  loading: boolean;
  empty: string;
}) {
  return (
    <div className="overflow-x-auto rounded-2xl border border-border bg-surface shadow-card" aria-busy={loading || undefined}>
      <table className="w-full min-w-[40rem] text-left text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead className="border-b border-border text-xs tracking-wide text-ink-muted uppercase">
          <tr>
            {columns.map((c) => (
              <th key={c.key} scope="col" className={`px-4 py-3 font-medium whitespace-nowrap ${c.numeric ? "text-right" : ""}`}>
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className={`divide-y divide-border transition-opacity ${loading && rows.length ? "opacity-60" : ""}`}>
          {rows.length === 0 && loading && [0, 1, 2].map((i) => (
            <tr key={`skeleton-${i}`}>
              {columns.map((c) => <td key={c.key} className="px-4 py-3"><Skeleton className="h-4 w-full max-w-32" /></td>)}
            </tr>
          ))}
          {rows.length === 0 && !loading && (
            <tr>
              <td colSpan={columns.length} className="px-4 py-10 text-center">
                <span className="inline-flex flex-col items-center gap-2 text-sm text-ink-muted">
                  <Inbox aria-hidden="true" className="size-5" />
                  {empty}
                </span>
              </td>
            </tr>
          )}
          {rows.map((row) => (
            <tr key={rowKey(row)} data-testid="report-row" className="align-top transition-colors hover:bg-surface-subtle">
              {columns.map((c) => (
                <td key={c.key} className={`px-4 py-3 text-ink ${c.numeric ? "text-right tabular-nums" : ""} ${c.className ?? ""}`}>
                  {c.cell(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length === 0 && loading && <p role="status" className="sr-only">Loading report…</p>}
    </div>
  );
}

/** Forward-only paging (the API's cursor): how many are shown of how many, and "Load more". */
export function LoadMore({ shown, total, hasMore, loading, onMore }: {
  shown: number; total: number | null; hasMore: boolean; loading: boolean; onMore: () => void;
}) {
  if (!shown) return null;
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 text-sm text-ink-muted">
      <p aria-live="polite">Showing {shown.toLocaleString()}{total !== null ? ` of ${total.toLocaleString()}` : ""}</p>
      {hasMore && <Button variant="secondary" onClick={onMore} loading={loading}>Load more</Button>}
    </div>
  );
}

// ------------------------------------------------------------------------------------------ export
/** Downloads the server's CSV for the report as it is shown (same range and filters). */
export function ExportButton({ report, range, filters, disabled = false }: {
  report: ExportReport; range: RangeChoice | null; filters?: object; disabled?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onClick() {
    setBusy(true);
    setError(null);
    try {
      const name = await downloadReportCsv(report, range, filters);
      toast.success(`Downloaded ${name}`);
    } catch (e) {
      setError(e instanceof ApiError ? reportErrorMessage(e) : "The export could not be downloaded. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col items-end gap-1.5">
      <Button variant="secondary" onClick={onClick} loading={busy} disabled={disabled}>
        {!busy && <FileDown aria-hidden="true" />} Export CSV
      </Button>
      {error && <p role="alert" className="max-w-xs text-right text-sm text-danger">{error}</p>}
    </div>
  );
}

// ------------------------------------------------------------------------------------------ filters
/**
 * Filters: a row of fields on wide screens; behind a "Filters" button on narrow ones. Changes apply on
 * "Apply" (one request, not one per keystroke).
 */
export function FilterPanel({ active, onApply, onReset, children }: {
  active: number; onApply: () => void; onReset: () => void; children: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <div className="rounded-2xl border border-border bg-surface p-4 shadow-card">
      <Button variant="ghost" size="sm" className="lg:hidden" aria-expanded={open} aria-controls={id}
              onClick={() => setOpen(!open)}>
        <SlidersHorizontal aria-hidden="true" /> Filters{active ? ` (${active})` : ""}
      </Button>
      <form id={id} onSubmit={(e) => { e.preventDefault(); onApply(); }}
            className={`${open ? "mt-3 grid" : "hidden"} gap-3 sm:grid-cols-2 lg:mt-0 lg:grid lg:grid-cols-4 lg:items-end`}>
        {children}
        <div className="flex items-end gap-2 sm:col-span-2 lg:col-span-4 lg:justify-end">
          <Button type="button" variant="ghost" onClick={onReset}>Reset filters</Button>
          <Button type="submit">Apply filters</Button>
        </div>
      </form>
    </div>
  );
}

export type Option = { id: string; label: string };

/**
 * A searchable choice from a long list (hosts, operators): the browser's own type-ahead (a datalist).
 * The value is the chosen option's id; text that matches no option selects nothing.
 */
export function LookupField({ label, options, value, onChange, placeholder }: {
  label: string; options: Option[]; value: string; onChange: (id: string) => void; placeholder?: string;
}) {
  const listId = useId();
  const selected = options.find((o) => o.id === value)?.label ?? "";
  const [text, setText] = useState(selected);
  // eslint-disable-next-line react-hooks/set-state-in-effect -- show the chosen option (or a reset)
  useEffect(() => { setText(selected); }, [selected]);
  return (
    <>
      <TextField label={label} value={text} list={listId} placeholder={placeholder} autoComplete="off"
                 onChange={(e) => {
                   setText(e.target.value);
                   onChange(options.find((o) => o.label === e.target.value)?.id ?? "");
                 }} />
      <datalist id={listId}>
        {options.map((o) => <option key={o.id} value={o.label} />)}
      </datalist>
    </>
  );
}

/** Unique, readable labels for the lookups (two hosts with one name are told apart by department). */
export function uniqueOptions(items: { id: string; label: string }[]): Option[] {
  const seen = new Map<string, number>();
  return items.map((item) => {
    const n = (seen.get(item.label) ?? 0) + 1;
    seen.set(item.label, n);
    return { id: item.id, label: n === 1 ? item.label : `${item.label} (${n})` };
  });
}
