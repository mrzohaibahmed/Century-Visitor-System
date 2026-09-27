import { describe, expect, it } from "vitest";

import type { Host } from "@/lib/api/directory";

import { EMPTY_DRAFT, toCheckIn, validateDraft } from "./draft";

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
    const belongings = Array.from({ length: 11 }, (_, i) => `item${i}`).join(",");
    expect(validateDraft({ ...EMPTY_DRAFT, host: HOST, reason: "INTERVIEW", belongings }).belongings).toBeDefined();
  });
});

describe("toCheckIn", () => {
  it("builds the request for a listed host", () => {
    expect(toCheckIn("v1", {
      ...EMPTY_DRAFT, host: HOST, reason: "INTERVIEW", vehicle: " lea 1234 ", belongings: "laptop, bag",
    })).toEqual({
      visitor_id: "v1", host_id: "h1", unlisted_host_name: null, department_id: "d1", reason_code: "INTERVIEW",
      reason_note: null, vehicle_registration: "lea 1234", belongings: ["laptop", "bag"],
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
