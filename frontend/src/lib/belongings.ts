/** Personal Material Returnable slip: draft types and conversion to/from stored visit belongings. */
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

/** Wire/storage shape used by the API. Older visits do not have this object. */
export type StoredPersonalMaterial = {
  contact_name: string;
  date: string | null;
  items: { description: string; qty_in: string | null; qty_out: string | null }[];
  remarks: string;
  authorised_by: string;
  issued_by: string;
  gate_officer: string;
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
  const suffix = qty ? ` (${qty})` : "";
  return desc.slice(0, MAX_BELONGING_LENGTH - suffix.length) + suffix;
}

export function belongingsList(pm: PersonalMaterial): string[] {
  return filledBelongings(pm).map(formatBelonging);
}

/** Rebuild slip rows from the strings stored on a visit (quantity in parentheses when present). */
export function belongingsFromStored(list: string[]): BelongingItem[] {
  if (!list.length) return [emptyBelongingItem()];
  return list.map((raw) => {
    const match = raw.match(/^(.*)\s*\((\d{1,4})\)\s*$/);
    if (match) return { description: match[1].trim(), qtyIn: match[2], qtyOut: "" };
    return { description: raw, qtyIn: "", qtyOut: "" };
  });
}

export function storedPersonalMaterial(pm: PersonalMaterial): StoredPersonalMaterial {
  return {
    contact_name: pm.contactName.trim(),
    date: pm.date || null,
    items: filledBelongings(pm).map((item) => ({
      description: item.description.trim(),
      qty_in: item.qtyIn.trim() || null,
      qty_out: item.qtyOut.trim() || null,
    })),
    remarks: pm.remarks.trim(),
    authorised_by: pm.authorisedBy.trim(),
    issued_by: pm.issuedBy.trim(),
    gate_officer: pm.gateOfficer.trim(),
  };
}

export function personalMaterialFromVisit(
  belongings: string[], contactName = "", stored?: StoredPersonalMaterial | null,
): PersonalMaterial {
  if (stored) {
    return {
      contactName: stored.contact_name,
      date: stored.date ?? "",
      items: stored.items.length ? stored.items.map((item) => ({
        description: item.description,
        qtyIn: item.qty_in ?? "",
        qtyOut: item.qty_out ?? "",
      })) : [emptyBelongingItem()],
      remarks: stored.remarks,
      authorisedBy: stored.authorised_by,
      issuedBy: stored.issued_by,
      gateOfficer: stored.gate_officer,
    };
  }
  return {
    ...emptyPersonalMaterial(),
    contactName,
    items: belongingsFromStored(belongings),
  };
}
