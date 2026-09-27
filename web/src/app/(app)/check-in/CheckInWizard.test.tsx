import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/client";
import type { Host } from "@/lib/api/directory";
import type { Visitor, VisitorWithStatus } from "@/lib/api/visitors";
import type { Visit } from "@/lib/api/visits";

const api = {
  lookupVisitor: vi.fn(), createVisitor: vi.fn(), getVisitor: vi.fn(), checkIn: vi.fn(), checkOut: vi.fn(),
  listHosts: vi.fn(), listDepartments: vi.fn(),
};
vi.mock("@/lib/api/visitors", async (original) => ({
  ...(await original<typeof import("@/lib/api/visitors")>()),
  lookupVisitor: (...a: unknown[]) => api.lookupVisitor(...a),
  createVisitor: (...a: unknown[]) => api.createVisitor(...a),
  getVisitor: (...a: unknown[]) => api.getVisitor(...a),
}));
vi.mock("@/lib/api/visits", async (original) => ({
  ...(await original<typeof import("@/lib/api/visits")>()),
  checkIn: (...a: unknown[]) => api.checkIn(...a),
  checkOut: (...a: unknown[]) => api.checkOut(...a),
}));
vi.mock("@/lib/api/directory", () => ({
  listHosts: (...a: unknown[]) => api.listHosts(...a),
  listDepartments: (...a: unknown[]) => api.listDepartments(...a),
}));

const { CheckInWizard } = await import("./CheckInWizard");

const VISITOR: Visitor = {
  id: "v1", full_name: "Ali Khan", identity: { type: "CNIC", number: "35201-1234567-1" }, phone: null,
  created_at: "", updated_at: "", active_visit: null,
};
const CLEAR: VisitorWithStatus = { visitor: VISITOR, screening: { status: "CLEAR", reason: null } };
const HOST: Host = {
  id: "h1", name: "Sara Ahmed", email: null, phone: null, department_id: "d1", department_name: "HR", is_active: true,
};
const ref = (id: string, name: string) => ({ id, name });
const VISIT: Visit = {
  id: "visit1", visit_number: "V-2026-000042", status: "CHECKED_IN", visitor: ref("v1", "Ali Khan"),
  host: ref("h1", "Sara Ahmed"), host_unlisted: false, department: ref("d1", "HR"), gate: ref("g1", "Main Gate"),
  checkout_gate: null, reason_code: "INTERVIEW", reason_note: null, vehicle_registration: null, belongings: [],
  check_in_at: "2026-09-27T08:00:00Z", check_out_at: null, checked_in_by: ref("u1", "Guard"), checked_out_by: null,
  checkout_method: null,
};

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  api.listHosts.mockResolvedValue([HOST]);
  api.listDepartments.mockResolvedValue([{ id: "d1", name: "HR", notification_email: null, is_active: true }]);
});
afterEach(cleanup);

function findVisitor(number = "3520112345671") {
  render(<CheckInWizard />);
  fireEvent.change(screen.getByLabelText("ID number"), { target: { value: number } });
  fireEvent.click(screen.getByRole("button", { name: "Find visitor" }));
}

describe("CheckInWizard", () => {
  it("asks for the visitor's details when the ID is not registered", async () => {
    api.lookupVisitor.mockRejectedValue(new ApiError(404, "not_found", "No visitor is registered with this ID number."));
    findVisitor();
    expect(await screen.findByText("New visitor")).toBeTruthy();
    expect(api.lookupVisitor).toHaveBeenCalledWith("CNIC", "3520112345671");
  });

  it("shows the server's message for an invalid ID number", async () => {
    api.lookupVisitor.mockRejectedValue(new ApiError(422, "invalid_identity", "A CNIC must have exactly 13 digits."));
    findVisitor("123");
    expect(await screen.findByText("A CNIC must have exactly 13 digits.")).toBeTruthy();
  });

  it("stops at a watchlist match and never offers check-in", async () => {
    api.lookupVisitor.mockResolvedValue({ ...CLEAR, screening: { status: "BLOCKED", reason: "Theft." } });
    findVisitor();
    expect((await screen.findByTestId("entry-denied")).textContent).toMatch(/Theft\./);
    expect(screen.queryByRole("button", { name: /Review/ })).toBeNull();
  });

  it("warns when the visitor is already inside", async () => {
    api.lookupVisitor.mockResolvedValue({ ...CLEAR, visitor: { ...VISITOR, active_visit: {
      id: "old", visit_number: "V-2026-000001", check_in_at: "2026-09-27T07:00:00Z", gate_name: "Main Gate" } } });
    findVisitor();
    expect(await screen.findByText(/V-2026-000001/)).toBeTruthy();
  });

  it("checks a known visitor in and shows the visit number", async () => {
    api.lookupVisitor.mockResolvedValue(CLEAR);
    api.checkIn.mockResolvedValue(VISIT);
    findVisitor();
    fireEvent.click(await screen.findByRole("button", { name: /Sara Ahmed/ }));
    fireEvent.change(screen.getByLabelText("Reason for visit"), { target: { value: "INTERVIEW" } });
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    fireEvent.click(await screen.findByRole("button", { name: "Confirm check-in" }));
    expect((await screen.findByTestId("visit-number")).textContent).toBe("V-2026-000042");
    expect(api.checkIn).toHaveBeenCalledWith(expect.objectContaining({
      visitor_id: "v1", host_id: "h1", department_id: "d1", reason_code: "INTERVIEW" }));
  });

  it("does not continue without a host and reason", async () => {
    api.lookupVisitor.mockResolvedValue(CLEAR);
    findVisitor();
    fireEvent.click(await screen.findByRole("button", { name: "Review" }));
    expect(screen.getByText("Choose the person being visited.")).toBeTruthy();
    expect(screen.getByText("Choose the reason for the visit.")).toBeTruthy();
  });

  it("switches to the denial screen if the server refuses entry at confirmation", async () => {
    api.lookupVisitor.mockResolvedValue(CLEAR);
    api.checkIn.mockRejectedValue(new ApiError(403, "entry_denied", "Entry denied: this person is on the watchlist."));
    findVisitor();
    fireEvent.click(await screen.findByRole("button", { name: /Sara Ahmed/ }));
    fireEvent.change(screen.getByLabelText("Reason for visit"), { target: { value: "INTERVIEW" } });
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    fireEvent.click(await screen.findByRole("button", { name: "Confirm check-in" }));
    await waitFor(() => expect(screen.getByTestId("entry-denied")).toBeTruthy());
  });
});
