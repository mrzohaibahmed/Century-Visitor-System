import { describe, expect, it } from "vitest";

import type { Host } from "@/lib/api/directory";

import {
  emptyBelongingItem, EMPTY_DRAFT, emptyPersonalMaterial, formatBelonging, toCheckIn, validateDraft,
} from "./draft";

const HOST: Host = {
  id: "h1", name: "Sara Ahmed", email: null, phone: null, department_id: "d1", department_name: "HR", is_active: true, linked_user: null,
};

describe("validateDraft", () => {
  it("requires a host, a department and a reason", () => {
    expect(Object.keys(validateDraft(EMPTY_DRAFT)).sort()).toEqual(["department", "host", "reason"]);
  });

  it("takes the department from the host", () => {
    expect(validateDraft({ ...EMPTY_DRAFT, host: HOST, reason: "INTERVIEW" })).toEqual({});
  });

  it("needs a department and a name for a host who is not listed", () => {
    const errors = validateDraft({ ...EMPTY_DRAFT, unlistedHost: true, host: HOST, reason: "DELIVERY" });
    expect(errors.host).toMatch(/name/);
    expect(errors.department).toBeDefined();
  });

  it("needs a description when the reason is Other", () => {
    expect(validateDraft({ ...EMPTY_DRAFT, host: HOST, reason: "OTHER" }).reasonNote).toBeDefined();
  });

  it("limits belongings to ten items", () => {
    const items = Array.from({ length: 11 }, (_, i) => ({
      ...emptyBelongingItem(), description: `item${i}`, qtyIn: "1",
    }));
    const personalMaterial = { ...emptyPersonalMaterial(), items };
    expect(validateDraft({ ...EMPTY_DRAFT, host: HOST, reason: "INTERVIEW", personalMaterial }).belongings).toBeDefined();
  });
});

describe("formatBelonging", () => {
  it("appends quantity in when present", () => {
    expect(formatBelonging({ description: "Laptop", qtyIn: "01", qtyOut: "" })).toBe("Laptop (01)");
  });

  it("uses the description alone when quantity is empty", () => {
    expect(formatBelonging({ description: "Bag", qtyIn: "", qtyOut: "" })).toBe("Bag");
  });
});

describe("toCheckIn", () => {
  it("builds the request for a listed host", () => {
    const personalMaterial = {
      ...emptyPersonalMaterial(),
      date: "2026-10-09",
      contactName: "Sara Ahmed",
      remarks: "Seal checked",
      authorisedBy: "Manager",
      issuedBy: "Guard One",
      gateOfficer: "Guard Two",
      items: [
        { description: "laptop", qtyIn: "", qtyOut: "1" },
        { description: "bag", qtyIn: "2", qtyOut: "2" },
      ],
    };
    expect(toCheckIn("v1", {
      ...EMPTY_DRAFT, host: HOST, reason: "INTERVIEW", vehicle: " lea 1234 ", personalMaterial,
    })).toEqual({
      visitor_id: "v1", host_id: "h1", unlisted_host_name: null, department_id: "d1", reason_code: "INTERVIEW",
      reason_note: null, vehicle_registration: "lea 1234", belongings: ["laptop", "bag (2)"],
      personal_material: {
        contact_name: "Sara Ahmed", date: "2026-10-09",
        items: [
          { description: "laptop", qty_in: null, qty_out: "1" },
          { description: "bag", qty_in: "2", qty_out: "2" },
        ],
        remarks: "Seal checked", authorised_by: "Manager", issued_by: "Guard One", gate_officer: "Guard Two",
      },
    });
  });

  it("sends only the typed name for an unlisted host, with the chosen department", () => {
    const body = toCheckIn("v1", {
      ...EMPTY_DRAFT, host: HOST, unlistedHost: true, unlistedHostName: " Bilal Shah ", departmentId: "d2",
      reason: "OTHER", reasonNote: " Audit ",
    });
    expect(body).toMatchObject({ host_id: null, unlisted_host_name: "Bilal Shah", department_id: "d2",
      reason_note: "Audit" });
  });
});
