import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Visit } from "@/lib/api/visits";

const api = { activeVisits: vi.fn(), checkOut: vi.fn(), checkOutBy: vi.fn() };
vi.mock("@/lib/api/visits", async (original) => ({
  ...(await original<typeof import("@/lib/api/visits")>()),
  activeVisits: (...a: unknown[]) => api.activeVisits(...a),
  checkOut: (...a: unknown[]) => api.checkOut(...a),
  checkOutBy: (...a: unknown[]) => api.checkOutBy(...a),
}));

const { CheckOutDesk, checkOutTarget } = await import("./CheckOutDesk");

const ref = (id: string, name: string) => ({ id, name });
const VISIT: Visit = {
  id: "visit1", visit_number: "V-2026-000042", status: "CHECKED_IN", visitor: ref("v1", "Ali Khan"),
  host: ref("h1", "Sara Ahmed"), host_unlisted: false, department: ref("d1", "HR"), gate: ref("g1", "Main Gate"),
  checkout_gate: null, reason_code: "INTERVIEW", reason_note: null, vehicle_registration: null, belongings: ["laptop"],
  check_in_at: "2026-09-27T08:00:00Z", check_out_at: null, checked_in_by: ref("u1", "Guard"), checked_out_by: null,
  checkout_method: null,
};
const OUT = { ...VISIT, status: "CHECKED_OUT" as const, check_out_at: "2026-09-27T09:00:00Z" };

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  api.activeVisits.mockResolvedValue({ items: [VISIT], total: 1 });
});
afterEach(cleanup);

describe("checkOutTarget", () => {
  it("recognises visit numbers in any case", () => {
    expect(checkOutTarget(" v-2026-000042 ", "CNIC")).toEqual({ visit_number: "V-2026-000042" });
  });

  it("treats anything else as an ID number of the chosen type", () => {
    expect(checkOutTarget("3520112345671", "CNIC")).toEqual({ identity: { type: "CNIC", number: "3520112345671" } });
  });
});

describe("CheckOutDesk", () => {
  it("lists visitors inside and checks one out after confirmation", async () => {
    api.checkOut.mockResolvedValue({ visit: OUT, already_checked_out: false });
    render(<CheckOutDesk />);
    expect(await screen.findByText("Ali Khan")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Check out Ali Khan (V-2026-000042)" }));
    expect(screen.getByText(/Belongings recorded at entry: laptop/)).toBeTruthy();
    // jsdom has no <dialog>.showModal(), so the modal's content counts as hidden.
    fireEvent.click(screen.getByRole("button", { name: "Confirm check-out", hidden: true }));
    expect(await screen.findByText(/checked out\. Time inside: 1 h 00 min/)).toBeTruthy();
    expect(api.checkOut).toHaveBeenCalledWith("visit1");
  });

  it("checks out by a typed visit number and reports a repeat as already done", async () => {
    api.checkOutBy.mockResolvedValue({ visit: OUT, already_checked_out: true });
    render(<CheckOutDesk />);
    fireEvent.change(screen.getByLabelText("Visit number or ID number"), { target: { value: "V-2026-000042" } });
    fireEvent.submit(screen.getByLabelText("Visit number or ID number").closest("form")!);
    await waitFor(() => expect(api.checkOutBy).toHaveBeenCalledWith({ visit_number: "V-2026-000042" }));
    expect(await screen.findByText(/was already checked out/)).toBeTruthy();
  });
});
