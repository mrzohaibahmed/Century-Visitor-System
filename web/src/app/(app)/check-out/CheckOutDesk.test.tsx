import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Visit } from "@/lib/api/visits";

const api = { activeVisits: vi.fn(), checkOut: vi.fn(), checkOutBy: vi.fn(), resolvePass: vi.fn(), checkOutWithPass: vi.fn(),
  issuePass: vi.fn() };
vi.mock("@/lib/api/visits", async (original) => ({
  ...(await original<typeof import("@/lib/api/visits")>()),
  activeVisits: (...a: unknown[]) => api.activeVisits(...a),
  checkOut: (...a: unknown[]) => api.checkOut(...a),
  checkOutBy: (...a: unknown[]) => api.checkOutBy(...a),
}));

vi.mock("@/lib/api/passes", async (original) => ({
  ...(await original<typeof import("@/lib/api/passes")>()),
  resolvePass: (...a: unknown[]) => api.resolvePass(...a),
  checkOutWithPass: (...a: unknown[]) => api.checkOutWithPass(...a),
  issuePass: (...a: unknown[]) => api.issuePass(...a),
}));

const { CheckOutDesk, checkOutTarget } = await import("./CheckOutDesk");
const PASS = `CGP1:${"A".repeat(64)}`;

const ref = (id: string, name: string) => ({ id, name });
const VISIT: Visit = {
  id: "visit1", visit_number: "V-2026-000042", status: "CHECKED_IN", visitor: ref("v1", "Ali Khan"),
  host: ref("h1", "Sara Ahmed"), host_unlisted: false, department: ref("d1", "HR"), gate: ref("g1", "Main Gate"),
  checkout_gate: null, reason_code: "INTERVIEW", reason_note: null, vehicle_registration: null, belongings: ["laptop"],
  check_in_at: "2026-09-27T08:00:00Z", check_out_at: null, checked_in_by: ref("u1", "Guard"), checked_out_by: null,
  checkout_method: null, photo_id: null,
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

describe("CheckOutDesk with a scanned badge", () => {
  function scanIntoBox(text: string) {
    const box = screen.getByLabelText("Visit number or ID number");
    fireEvent.change(box, { target: { value: text } });
    fireEvent.submit(box.closest("form")!);
  }

  it("looks the pass up and only checks out after confirmation", async () => {
    api.resolvePass.mockResolvedValue({ status: "VALID", visit: { ...VISIT, photo_id: "p1" } });
    api.checkOutWithPass.mockResolvedValue({ visit: { ...OUT, checkout_method: "QR" }, already_checked_out: false });
    render(<CheckOutDesk />);
    scanIntoBox(`${PASS}\r\n`);          // USB scanners end with Enter
    const confirm = await screen.findByTestId("scan-confirm");
    expect(api.resolvePass).toHaveBeenCalledWith(PASS);
    expect(api.checkOutWithPass).not.toHaveBeenCalled();                       // scanning alone changes nothing
    expect(confirm.textContent).toMatch(/Ali Khan.*V-2026-000042.*Sara Ahmed/);
    expect(confirm.querySelector("img")?.getAttribute("src")).toBe("/api/v1/photos/p1");
    expect(confirm.textContent).toMatch(/Belongings recorded at entry: laptop/);
    fireEvent.click(screen.getByRole("button", { name: "Confirm check-out", hidden: true }));
    expect(await screen.findByText(/checked out\. Time inside/)).toBeTruthy();
    expect(api.checkOutWithPass).toHaveBeenCalledWith(PASS);
    expect(api.checkOutBy).not.toHaveBeenCalled();
  });

  it("says so when the badge belongs to a visit that already ended", async () => {
    api.resolvePass.mockResolvedValue({ status: "CHECKED_OUT", visit: OUT });
    render(<CheckOutDesk />);
    scanIntoBox(PASS);
    expect((await screen.findByTestId("scan-confirm")).textContent).toMatch(/already checked out.*Nothing was changed/);
    expect(screen.queryByRole("button", { name: "Confirm check-out", hidden: true })).toBeNull();
  });

  it("shows why a pass is refused", async () => {
    const { ApiError } = await import("@/lib/api/client");
    api.resolvePass.mockRejectedValue(new ApiError(409, "pass_replaced", "This badge has been replaced by a newer one."));
    render(<CheckOutDesk />);
    scanIntoBox(PASS);
    expect(await screen.findByText("This badge has been replaced by a newer one.")).toBeTruthy();
    expect(screen.queryByTestId("scan-confirm")).toBeNull();
  });

  it("reprints a badge only after warning that the old one stops working", async () => {
    api.issuePass.mockResolvedValue({ qr_text: PASS, expires_at: "2026-09-28T08:00:00Z", badge: {
      organization: "Century Gate", visitor_name: "Ali Khan", visit_number: "V-2026-000042", host_name: "Sara Ahmed",
      department_name: "HR", gate_name: "Main Gate", check_in_at: VISIT.check_in_at, valid_until: "2026-09-28T08:00:00Z" } });
    render(<CheckOutDesk />);
    fireEvent.click(await screen.findByRole("button", { name: "Reprint badge for Ali Khan (V-2026-000042)" }));
    expect(screen.getByText(/cancels the old one/)).toBeTruthy();
    expect(api.issuePass).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Issue new badge", hidden: true }));
    expect(await screen.findByText(/The previous badge no longer works/)).toBeTruthy();
    expect(api.issuePass).toHaveBeenCalledWith("visit1");
  });
});
