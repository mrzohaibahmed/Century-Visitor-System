/** The visit-details form of the check-in wizard: validation and the request it produces. */
import type { Host } from "@/lib/api/directory";
import type { CheckIn, VisitReason } from "@/lib/api/visits";
import {
  belongingsList,
  emptyPersonalMaterial,
  filledBelongings,
  MAX_BELONGINGS,
  type PersonalMaterial,
} from "@/lib/belongings";

export {
  belongingsList, emptyBelongingItem, emptyPersonalMaterial, filledBelongings, formatBelonging,
  MAX_BELONGING_LENGTH, MAX_BELONGINGS, type BelongingItem, type PersonalMaterial,
} from "@/lib/belongings";

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

export const EMPTY_DRAFT: VisitDraft = {
  host: null, unlistedHost: false, unlistedHostName: "", departmentId: "", reason: "", reasonNote: "",
  vehicle: "", personalMaterial: emptyPersonalMaterial(),
};

export type DraftErrors = Partial<Record<"host" | "department" | "reason" | "reasonNote" | "belongings", string>>;

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
