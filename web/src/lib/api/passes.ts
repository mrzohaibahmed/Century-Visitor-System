import { apiRequest } from "./client";
import type { CheckOutResult, Visit } from "./visits";

/** Mirrors app/schemas/passes.py. */
export type Badge = {
  organization: string;
  visitor_name: string;
  visit_number: string;
  host_name: string | null;
  department_name: string | null;
  gate_name: string | null;
  check_in_at: string;
  valid_until: string;
};

/** Returned once for printing. Printing again means issuing a new pass, which cancels this one. */
export type IssuedPass = { qr_text: string; expires_at: string; badge: Badge };

export type ScanResult = { status: "VALID" | "CHECKED_OUT"; visit: Visit };

export const PASS_PREFIX = "CGP1:";

/** True when a typed or scanned value is one of our passes (USB scanners type it into a text box). */
export function looksLikePass(text: string): boolean {
  return text.trim().toUpperCase().startsWith(PASS_PREFIX);
}

export function issuePass(visitId: string): Promise<IssuedPass> {
  return apiRequest<IssuedPass>(`/visits/${encodeURIComponent(visitId)}/pass`, { method: "POST" });
}

export function recordBadgePrint(visitId: string): Promise<void> {
  return apiRequest<void>(`/visits/${encodeURIComponent(visitId)}/badge-print`, { method: "POST" });
}

/** Who the pass belongs to. Changes nothing; the guard confirms before checking out. */
export function resolvePass(qrText: string): Promise<ScanResult> {
  return apiRequest<ScanResult>("/passes/resolve", { method: "POST", body: { qr_text: qrText } });
}

export function checkOutWithPass(qrText: string): Promise<CheckOutResult> {
  return apiRequest<CheckOutResult>("/passes/check-out", { method: "POST", body: { qr_text: qrText } });
}
