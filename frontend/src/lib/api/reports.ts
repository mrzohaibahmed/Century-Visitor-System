/**
 * Reports (administrators only; the API enforces reports:view on every call).
 * Mirrors backend/app/schemas/reports.py and the query parameters of backend/app/api/v1/reports.py.
 *
 * The server does all the work: date ranges (Asia/Karachi days), filtering, aggregation, totals and
 * masking (ID numbers and phones arrive masked). The browser only asks and shows.
 */
import { ApiError, apiBlob, apiRequest } from "./client";
import type { VisitReason, VisitStatus } from "./visits";

export type RangePreset = "today" | "yesterday" | "this_week" | "this_month" | "custom";

/** What the user chose. `from`/`to` (YYYY-MM-DD) only with "custom". */
export type RangeChoice = { range: RangePreset; from?: string; to?: string };

/** The period the server actually used (presets resolved on the server). */
export type ReportRange = { preset: RangePreset; from: string; to: string; timezone: string };

export type Ref = { id: string | null; name: string | null };

// ------------------------------------------------------------------------------------------ overview
export type OverviewTotals = {
  visits: number;
  unique_visitors: number;
  /** Current state: visitors inside right now, whatever the range. */
  inside_now: number;
  checked_out: number;
  denied_entries: number;
  watchlist_matches: number;
  /** Completed visits only; null when none completed. */
  avg_duration_minutes: number | null;
};

export type Overview = {
  range: ReportRange;
  generated_at: string;
  totals: OverviewTotals;
  series: {
    bucket: "hour" | "day";
    /** Every bucket of the range; `start` is ISO 8601 in the organisation's time zone (e.g. +05:00). */
    over_time: { start: string; count: number }[];
    by_department: { id: string | null; name: string | null; count: number }[];
    by_status: { status: string; count: number }[];
    peak_hours: { hour: number; count: number }[];
  };
};

// ------------------------------------------------------------------------------------------ rows
export type VisitReportRow = {
  id: string;
  visit_number: string;
  visitor: Ref;
  id_type: string | null;
  /** Masked by the server. */
  id_number: string | null;
  /** Masked by the server. */
  phone: string | null;
  host: Ref;
  host_unlisted: boolean;
  department: Ref;
  reason_code: VisitReason;
  reason_note: string | null;
  gate: Ref;
  check_in_at: string;
  check_out_at: string | null;
  duration_minutes: number;
  status: VisitStatus;
  checked_in_by: Ref;
  checked_out_by: Ref | null;
};

export type VisitorSummaryRow = {
  visitor: Ref;
  id_type: string | null;
  id_number: string | null;
  phone: string | null;
  visits: number;
  completed_visits: number;
  first_visit_at: string;
  last_visit_at: string;
  avg_duration_minutes: number | null;
  /** Current state. */
  inside_now: boolean;
};

export type HostRow = {
  host: Ref;
  host_unlisted: boolean;
  department: Ref;
  visits: number;
  completed_visits: number;
  inside_now: number;
};

export type DepartmentRow = {
  department: Ref;
  visits: number;
  completed_visits: number;
  unique_visitors: number;
  avg_duration_minutes: number | null;
  inside_now: number;
};

export type GuardRow = {
  guard: { id: string | null; name: string | null; role: string | null; is_active: boolean | null };
  check_ins: number;
  check_outs: number;
  inside_now: number;
  denied_entries: number;
  watchlist_matches: number;
};

export type DenialSource = "check_in" | "lookup" | "audit_backfill";

export type DenialRow = {
  id: string;
  at: string;
  reason: string;
  reason_code: VisitReason | null;
  source: DenialSource;
  visitor: Ref;
  /** Masked when recorded. */
  identifier: string | null;
  watchlist: { id: string | null; reason: string | null };
  gate: Ref;
  operator: Ref;
  /** Names filled from the current records (older rebuilt denials). */
  current_names: ("visitor" | "gate" | "operator")[];
};

// ------------------------------------------------------------------------------------------ pages
export type Keyset<T> = { items: T[]; next_cursor: string | null };
export type VisitReportPage = Keyset<VisitReportRow> & { range: ReportRange; total: number };
export type VisitorSummaryPage = Keyset<VisitorSummaryRow> & { range: ReportRange; total: number };
export type InsidePage = Keyset<VisitReportRow> & { generated_at: string; total: number };
export type DenialPage = Keyset<DenialRow> & {
  range: ReportRange; total: number; denied_entries: number; watchlist_matches: number;
};
export type GroupPage<T> = { range: ReportRange; items: T[]; total: number; truncated: boolean };

// ------------------------------------------------------------------------------------------ filters
export type VisitSort = "check_in_desc" | "check_in_asc" | "check_out_desc" | "duration_desc";
export type VisitorSort = "last_visit_desc" | "visits_desc";
export type InsideSort = "check_in_asc" | "check_in_desc";

export type VisitFilters = {
  q?: string; status?: VisitStatus | ""; host_id?: string; department_id?: string; gate_id?: string;
  guard_id?: string; reason_code?: VisitReason | ""; sort?: VisitSort;
};
export type VisitorFilters = { q?: string; host_id?: string; department_id?: string; gate_id?: string; sort?: VisitorSort };
export type InsideFilters = { q?: string; host_id?: string; department_id?: string; gate_id?: string; sort?: InsideSort };
export type DenialFilters = { source?: DenialSource | ""; guard_id?: string; gate_id?: string };
export type HostFilters = { department_id?: string };

/** The query string: only the values set; the range only where the report has one. */
export function reportQuery(range: RangeChoice | null, filters: object = {},
                            extra: Record<string, string | number | null | undefined> = {}): string {
  const params = new URLSearchParams();
  if (range) {
    params.set("range", range.range);
    if (range.range === "custom") {
      if (range.from) params.set("from", range.from);
      if (range.to) params.set("to", range.to);
    }
  }
  for (const [key, value] of Object.entries({ ...filters, ...extra })) {
    if (value !== undefined && value !== null && String(value).trim() !== "") params.set(key, String(value).trim());
  }
  const text = params.toString();
  return text ? `?${text}` : "";
}

type Opts = { signal?: AbortSignal };
const PAGE = 25;
const GROUPS = 500;          // the API's maximum for hosts, departments and guards

export function getOverview(range: RangeChoice, { signal }: Opts = {}): Promise<Overview> {
  return apiRequest<Overview>(`/reports/overview${reportQuery(range)}`, { signal });
}

export function getVisitReport(range: RangeChoice, filters: VisitFilters, cursor: string | null,
                               { signal }: Opts = {}): Promise<VisitReportPage> {
  return apiRequest(`/reports/visits${reportQuery(range, filters, { cursor, limit: PAGE })}`, { signal });
}

export function getVisitorReport(range: RangeChoice, filters: VisitorFilters, cursor: string | null,
                                 { signal }: Opts = {}): Promise<VisitorSummaryPage> {
  return apiRequest(`/reports/visitors${reportQuery(range, filters, { cursor, limit: PAGE })}`, { signal });
}

export function getHostReport(range: RangeChoice, filters: HostFilters, { signal }: Opts = {}): Promise<GroupPage<HostRow>> {
  return apiRequest(`/reports/hosts${reportQuery(range, filters, { limit: GROUPS })}`, { signal });
}

export function getDepartmentReport(range: RangeChoice, { signal }: Opts = {}): Promise<GroupPage<DepartmentRow>> {
  return apiRequest(`/reports/departments${reportQuery(range, {}, { limit: GROUPS })}`, { signal });
}

export function getGuardReport(range: RangeChoice, { signal }: Opts = {}): Promise<GroupPage<GuardRow>> {
  return apiRequest(`/reports/guards${reportQuery(range, {}, { limit: GROUPS })}`, { signal });
}

/** Current state: no date range. */
export function getInsideReport(filters: InsideFilters, cursor: string | null, { signal }: Opts = {}): Promise<InsidePage> {
  return apiRequest(`/reports/inside${reportQuery(null, filters, { cursor, limit: PAGE })}`, { signal });
}

export function getDenialReport(range: RangeChoice, filters: DenialFilters, cursor: string | null,
                                { signal }: Opts = {}): Promise<DenialPage> {
  return apiRequest(`/reports/denials${reportQuery(range, filters, { cursor, limit: PAGE })}`, { signal });
}

// ------------------------------------------------------------------------------------------ exports (CSV, XLSX)
export type ExportReport = "visits" | "visitors" | "hosts" | "departments" | "guards" | "inside" | "denials";
export type ExportFormat = "csv" | "xlsx" | "pdf";

const EXPORT_TYPES: Record<ExportFormat, string> = {
  csv: "text/csv",
  xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  pdf: "application/pdf",
};

/** The server's file name (Content-Disposition), or a fixed fallback. Never built from user input. */
export function fileNameFrom(disposition: string | null, report: ExportReport, format: ExportFormat = "csv"): string {
  const match = /filename="([^"]+)"/.exec(disposition ?? "");
  return match && /^[\w.-]+$/.test(match[1]) && match[1].endsWith(`.${format}`)
    ? match[1] : `century-gate-${report}.${format}`;
}

/** The server-generated CSV for exactly these filters and range. */
export function downloadReportCsv(report: ExportReport, range: RangeChoice | null, filters: object = {}): Promise<string> {
  return downloadReport(report, "csv", range, filters);
}

/** The server-generated Excel workbook for exactly these filters and range. */
export function downloadReportXlsx(report: ExportReport, range: RangeChoice | null, filters: object = {}): Promise<string> {
  return downloadReport(report, "xlsx", range, filters);
}

/** The server-generated PDF for exactly these filters and range. */
export function downloadReportPdf(report: ExportReport, range: RangeChoice | null, filters: object = {}): Promise<string> {
  return downloadReport(report, "pdf", range, filters);
}

/**
 * Downloads a report file for exactly these filters and range: the file is made by the API, never here.
 * Errors (e.g. too many rows) arrive as the usual ApiError.
 */
export async function downloadReport(report: ExportReport, format: ExportFormat, range: RangeChoice | null,
                                     filters: object = {}): Promise<string> {
  const type = EXPORT_TYPES[format];
  const { blob, headers } = await apiBlob(`/reports/${report}/export${reportQuery(range, filters, { format })}`,
                                          {}, `${type}, application/json`);
  if (!(headers.get("content-type") ?? "").startsWith(type)) {
    throw new ApiError(0, "unexpected_response", "The export could not be downloaded. Please try again.");
  }
  const name = fileNameFrom(headers.get("content-disposition"), report, format);
  const url = URL.createObjectURL(blob);
  try {
    const link = document.createElement("a");
    link.href = url;
    link.download = name;
    link.rel = "noopener";
    document.body.appendChild(link);
    link.click();
    link.remove();
  } finally {
    // Give the browser a moment to start the download before the memory is released.
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return name;
}
