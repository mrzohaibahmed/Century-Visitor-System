import { apiRequest } from "./client";
import type { Identity } from "./visitors";

/** Mirrors app/schemas/visits.py. */
export type Page<T> = { items: T[]; next_cursor: string | null };

export type VisitReason =
  | "OFFICIAL_MEETING" | "INTERVIEW" | "DELIVERY" | "MAINTENANCE" | "CONTRACTOR_WORK" | "PERSONAL" | "OTHER";

export const VISIT_REASONS: { value: VisitReason; label: string }[] = [
  { value: "OFFICIAL_MEETING", label: "Official meeting" },
  { value: "INTERVIEW", label: "Interview" },
  { value: "DELIVERY", label: "Delivery" },
  { value: "MAINTENANCE", label: "Maintenance" },
  { value: "CONTRACTOR_WORK", label: "Contractor work" },
  { value: "PERSONAL", label: "Personal" },
  { value: "OTHER", label: "Other" },
];

export function reasonLabel(code: string): string {
  return VISIT_REASONS.find((r) => r.value === code)?.label ?? code;
}

export type VisitStatus = "CHECKED_IN" | "CHECKED_OUT";
export type Ref = { id: string | null; name: string | null };

export type Visit = {
  id: string;
  visit_number: string;
  status: VisitStatus;
  visitor: Ref;
  host: Ref;
  host_unlisted: boolean;
  department: Ref;
  gate: Ref;
  checkout_gate: Ref | null;
  reason_code: VisitReason;
  reason_note: string | null;
  vehicle_registration: string | null;
  belongings: string[];
  check_in_at: string;
  check_out_at: string | null;
  checked_in_by: Ref;
  checked_out_by: Ref | null;
  checkout_method: string | null;
  photo_id: string | null;
};

export type CheckIn = {
  visitor_id: string;
  host_id?: string | null;
  unlisted_host_name?: string | null;
  department_id?: string | null;
  reason_code: VisitReason;
  reason_note?: string | null;
  vehicle_registration?: string | null;
  belongings?: string[];
  photo_id?: string | null;
};

export type CheckOutResult = { visit: Visit; already_checked_out: boolean };

export function checkIn(body: CheckIn): Promise<Visit> {
  return apiRequest<Visit>("/visits", { method: "POST", body });
}

export function activeVisits(signal?: AbortSignal): Promise<{ items: Visit[]; total: number }> {
  return apiRequest<{ items: Visit[]; total: number }>("/visits/active", { signal });
}

export function getVisit(id: string, signal?: AbortSignal): Promise<Visit> {
  return apiRequest<Visit>(`/visits/${encodeURIComponent(id)}`, { signal });
}

/** Idempotent: checking out a visit that is already out returns it with already_checked_out = true. */
export function checkOut(id: string): Promise<CheckOutResult> {
  return apiRequest<CheckOutResult>(`/visits/${encodeURIComponent(id)}/check-out`, { method: "POST" });
}

export const VISIT_NUMBER_PATTERN = /^V-\d{4}-\d{6,}$/i;

/** Check-out by a typed or scanned value: a visit number (V-2026-000123) or the visitor's ID number. */
export function checkOutBy(value: { visit_number: string } | { identity: Identity }): Promise<CheckOutResult> {
  return apiRequest<CheckOutResult>("/visits/check-out", { method: "POST", body: value });
}

export type VisitFilters = {
  status?: VisitStatus | "";
  from?: string;
  to?: string;
  host_id?: string;
  department_id?: string;
  gate_id?: string;
  q?: string;
};

export function visitQuery(filters: VisitFilters, cursor?: string | null): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value && String(value).trim()) params.set(key, String(value).trim());
  }
  if (cursor) params.set("cursor", cursor);
  const text = params.toString();
  return text ? `?${text}` : "";
}

export function listVisits(filters: VisitFilters, cursor?: string | null, signal?: AbortSignal): Promise<Page<Visit>> {
  return apiRequest<Page<Visit>>(`/visits${visitQuery(filters, cursor)}`, { signal });
}
