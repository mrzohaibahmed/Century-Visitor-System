/** The visit-details form of the check-in wizard: validation and the request it produces. */
import type { Host } from "@/lib/api/directory";
import type { CheckIn, VisitReason } from "@/lib/api/visits";
import { isoDay } from "@/lib/format";

export const MAX_BELONGINGS = 10;
/** Matches the backend Belonging max length. */
export const MAX_BELONGING_LENGTH = 40;

/** One row on the Personal Material Returnable slip. */
export type BelongingItem = {
  description: string;
  qtyIn: string;
  qtyOut: string;
};

/** Header / footer fields on the Personal Material Returnable slip (gate paperwork). */
export type PersonalMaterial = {
  contactName: string;
  date: string;
  items: BelongingItem[];
  remarks: string;
  authorisedBy: string;
  issuedBy: string;
  gateOfficer: string;
};

export type VisitDraft = {
  host: Host | null;
  unlistedHost: boolean;
  unlistedHostName: string;
  /** Empty: use the host's own department. */
  departmentId: string;
  reason: VisitReason | "";
  reasonNote: string;
  vehicle: string;
  personalMaterial: PersonalMaterial;
};

export function emptyBelongingItem(): BelongingItem {
  return { description: "", qtyIn: "", qtyOut: "" };
}

export function emptyPersonalMaterial(): PersonalMaterial {
  return {
    contactName: "",
    date: isoDay(),
    items: [emptyBelongingItem()],
    remarks: "",
    authorisedBy: "",
    issuedBy: "",
    gateOfficer: "",
  };
}

export const EMPTY_DRAFT: VisitDraft = {
  host: null, unlistedHost: false, unlistedHostName: "", departmentId: "", reason: "", reasonNote: "",
  vehicle: "", personalMaterial: emptyPersonalMaterial(),
};

export type DraftErrors = Partial<Record<"host" | "department" | "reason" | "reasonNote" | "belongings", string>>;

/** Rows that have a description (blank rows on the slip are ignored). */
export function filledBelongings(pm: PersonalMaterial): BelongingItem[] {
  return pm.items.filter((row) => row.description.trim());
}

/**
 * Turn a slip row into the string stored on the visit.
 * Quantity in is appended when present so checkout can still show "what and how many".
 */
export function formatBelonging(item: BelongingItem): string {
  const desc = item.description.trim();
  const qty = item.qtyIn.trim();
  const text = qty ? `${desc} (${qty})` : desc;
  return text.slice(0, MAX_BELONGING_LENGTH);
}

export function belongingsList(pm: PersonalMaterial): string[] {
  return filledBelongings(pm).map(formatBelonging);
}

export function validateDraft(d: VisitDraft): DraftErrors {
  const errors: DraftErrors = {};
  if (d.unlistedHost ? !d.unlistedHostName.trim() : !d.host) {
    errors.host = d.unlistedHost ? "Enter the name of the person being visited." : "Choose the person being visited.";
  }
  const hostDepartment = d.unlistedHost ? null : d.host?.department_id;
  if (!d.departmentId && !hostDepartment) errors.department = "Choose the department being visited.";
  if (!d.reason) errors.reason = "Choose the reason for the visit.";
  if (d.reason === "OTHER" && !d.reasonNote.trim()) errors.reasonNote = "Describe the reason.";
  if (filledBelongings(d.personalMaterial).length > MAX_BELONGINGS) {
    errors.belongings = `At most ${MAX_BELONGINGS} items.`;
  }
  return errors;
}

export function effectiveDepartmentId(d: VisitDraft): string | null {
  return d.departmentId || (d.unlistedHost ? null : d.host?.department_id) || null;
}

export function toCheckIn(visitorId: string, d: VisitDraft): CheckIn {
  return {
    visitor_id: visitorId,
    host_id: d.unlistedHost ? null : d.host?.id ?? null,
    unlisted_host_name: d.unlistedHost ? d.unlistedHostName.trim() : null,
    department_id: effectiveDepartmentId(d),
    reason_code: d.reason as VisitReason,
    reason_note: d.reasonNote.trim() || null,
    vehicle_registration: d.vehicle.trim() || null,
    belongings: belongingsList(d.personalMaterial),
  };
}
