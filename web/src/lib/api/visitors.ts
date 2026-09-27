import { apiRequest } from "./client";
import type { Page, Visit } from "./visits";

/** Mirrors app/schemas/visitors.py. */
export type IdentityType = "CNIC" | "PASSPORT" | "OTHER";
export type Identity = { type: IdentityType; number: string };

export const IDENTITY_LABELS: Record<IdentityType, string> = {
  CNIC: "CNIC",
  PASSPORT: "Passport",
  OTHER: "Other ID",
};

export type ActiveVisitRef = { id: string; visit_number: string; check_in_at: string; gate_name: string | null };

export type Visitor = {
  id: string;
  full_name: string;
  identity: Identity | null;
  phone: string | null;
  created_at: string;
  updated_at: string;
  active_visit: ActiveVisitRef | null;
  /** Current photo; the image is fetched from photoUrl(). */
  photo_id: string | null;
};

export type Screening = { status: "CLEAR" | "BLOCKED"; reason: string | null };
export type VisitorWithStatus = { visitor: Visitor; screening: Screening };

/** Check-in step 1. 404 (ApiError) when nobody is registered with this ID; the lookup is audited. */
export function lookupVisitor(type: IdentityType, number: string, signal?: AbortSignal): Promise<VisitorWithStatus> {
  const params = new URLSearchParams({ id_type: type, id_number: number.trim() });
  return apiRequest<VisitorWithStatus>(`/visitors/lookup?${params}`, { signal });
}

export function searchVisitors(q: string, cursor?: string | null, signal?: AbortSignal): Promise<Page<Visitor>> {
  const params = new URLSearchParams({ q: q.trim() });
  if (cursor) params.set("cursor", cursor);
  return apiRequest<Page<Visitor>>(`/visitors?${params}`, { signal });
}

export type NewVisitor = { full_name: string; identity: Identity; phone?: string | null };

export function createVisitor(visitor: NewVisitor): Promise<Visitor> {
  return apiRequest<Visitor>("/visitors", { method: "POST", body: visitor });
}

/** Opening a visitor's details is audited (personal data access). */
export function getVisitor(id: string, signal?: AbortSignal): Promise<VisitorWithStatus> {
  return apiRequest<VisitorWithStatus>(`/visitors/${encodeURIComponent(id)}`, { signal });
}

export function updateVisitor(id: string, changes: Partial<NewVisitor>): Promise<Visitor> {
  return apiRequest<Visitor>(`/visitors/${encodeURIComponent(id)}`, { method: "PATCH", body: changes });
}

export function visitorVisits(id: string, cursor?: string | null, signal?: AbortSignal): Promise<Page<Visit>> {
  const suffix = cursor ? `?${new URLSearchParams({ cursor })}` : "";
  return apiRequest<Page<Visit>>(`/visitors/${encodeURIComponent(id)}/visits${suffix}`, { signal });
}
