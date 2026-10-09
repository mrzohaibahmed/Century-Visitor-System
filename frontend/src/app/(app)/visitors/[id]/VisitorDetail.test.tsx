import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/client";
import type { Visitor, VisitorWithStatus } from "@/lib/api/visitors";
import type { Visit } from "@/lib/api/visits";

const api = {
  getVisitor: vi.fn(), updateVisitor: vi.fn(), visitorVisits: vi.fn(),
  getVisit: vi.fn(), updateVisitBelongings: vi.fn(),
};
const session = { canEdit: true };
const toastSuccess = vi.fn();
vi.mock("@/lib/api/visitors", async (original) => ({
  ...(await original<typeof import("@/lib/api/visitors")>()),
  getVisitor: (...a: unknown[]) => api.getVisitor(...a),
  updateVisitor: (...a: unknown[]) => api.updateVisitor(...a),
  visitorVisits: (...a: unknown[]) => api.visitorVisits(...a),
}));
vi.mock("@/lib/api/visits", async (original) => ({
  ...(await original<typeof import("@/lib/api/visits")>()),
  getVisit: (...a: unknown[]) => api.getVisit(...a),
  updateVisitBelongings: (...a: unknown[]) => api.updateVisitBelongings(...a),
}));
vi.mock("@/components/session/SessionProvider", () => ({
  useSession: () => ({ hasPermission: (p: string) => p === "visitor:edit" && session.canEdit }),
}));
vi.mock("sonner", () => ({ toast: { success: (...a: unknown[]) => toastSuccess(...a) } }));

const { VisitorDetail } = await import("./VisitorDetail");

const VISITOR: Visitor = {
  id: "v1", full_name: "Hamza Tariq", identity: { type: "CNIC", number: "35202-7654321-3" }, phone: "03001112223",
  created_at: "2026-09-27T08:00:00Z", updated_at: "2026-09-27T08:00:00Z", active_visit: null, photo_id: null,
};
const CLEAR: VisitorWithStatus = { visitor: VISITOR, screening: { status: "CLEAR", reason: null } };
const ref = (id: string, name: string) => ({ id, name });
const VISIT: Visit = {
  id: "visit1", visit_number: "V-2026-000042", status: "CHECKED_OUT", visitor: ref("v1", "Hamza Tariq"),
  host: ref("h1", "Sara Ahmed"), host_unlisted: false, department: ref("d1", "HR"), gate: ref("g1", "Main Gate"),
  checkout_gate: null, reason_code: "INTERVIEW", reason_note: null, vehicle_registration: null, belongings: [],
  check_in_at: "2026-09-27T08:00:00Z", check_out_at: "2026-09-27T09:00:00Z", checked_in_by: ref("u1", "Guard"),
  checked_out_by: null, checkout_method: null, photo_id: null,
};

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  toastSuccess.mockReset();
  session.canEdit = true;
  api.getVisitor.mockResolvedValue(CLEAR);
  api.visitorVisits.mockResolvedValue({ items: [VISIT], next_cursor: null });
  api.getVisit.mockResolvedValue({ ...VISIT, status: "CHECKED_IN", check_out_at: null, belongings: ["Laptop"] });
});
afterEach(cleanup);

describe("VisitorDetail", () => {
  it("shows a skeleton, then the record and its visits", async () => {
    render(<VisitorDetail id="v1" />);
    expect(screen.getByText("Loading visitor…")).toBeTruthy();
    expect(await screen.findByRole("heading", { level: 1, name: "Hamza Tariq" })).toBeTruthy();
    expect(screen.getByText("Not inside")).toBeTruthy();
    expect(screen.getByText("03001112223")).toBeTruthy();
    expect(await screen.findByTestId("visit-row")).toBeTruthy();
    expect(screen.getByTestId("visit-row").textContent).toMatch(/V-2026-000042.*Sara Ahmed.*Checked out/);
  });

  it("leaves out a missing phone and shows the current visit", async () => {
    api.getVisitor.mockResolvedValue({ ...CLEAR, visitor: { ...VISITOR, phone: null,
      active_visit: { id: "a1", visit_number: "V-2026-000050", check_in_at: "2026-09-27T10:00:00Z", gate_name: "Main Gate" } } });
    render(<VisitorDetail id="v1" />);
    expect(await screen.findByText("Current visit")).toBeTruthy();
    expect(screen.queryByText("Phone")).toBeNull();
    expect(screen.getByText(/Inside since .* \(V-2026-000050\)/)).toBeTruthy();
    expect(await screen.findByRole("heading", { name: "Belongings" })).toBeTruthy();
    expect(await screen.findByText("Laptop")).toBeTruthy();
  });

  it("opens the personal material form from belongings while the visitor is inside", async () => {
    api.getVisitor.mockResolvedValue({ ...CLEAR, visitor: { ...VISITOR,
      active_visit: { id: "a1", visit_number: "V-2026-000050", check_in_at: "2026-09-27T10:00:00Z", gate_name: "Main Gate" } } });
    api.getVisit.mockResolvedValue({ ...VISIT, id: "a1", status: "CHECKED_IN", check_out_at: null, belongings: [] });
    render(<VisitorDetail id="v1" />);
    fireEvent.click(await screen.findByRole("button", { name: /Add personal material/i }));
    expect(await screen.findByRole("heading", { name: "Personal Material Returnable", hidden: true })).toBeTruthy();
  });

  it("warns when the visitor is on the watchlist", async () => {
    api.getVisitor.mockResolvedValue({ ...CLEAR, screening: { status: "BLOCKED", reason: "Theft." } });
    render(<VisitorDetail id="v1" />);
    expect(await screen.findByText("On the watchlist: entry not permitted.")).toBeTruthy();
    expect(screen.getByText("On the watchlist")).toBeTruthy();
  });

  it("says when a visitor does not exist, without offering a retry", async () => {
    api.getVisitor.mockRejectedValue(new ApiError(404, "not_found", "Visitor not found."));
    render(<VisitorDetail id="missing" />);
    expect(await screen.findByRole("heading", { name: "Visitor not found" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
    expect(screen.getByRole("link", { name: "Visitors" }).getAttribute("href")).toBe("/visitors");
  });

  it("retries a record that failed to load", async () => {
    api.getVisitor.mockRejectedValueOnce(new ApiError(0, "network_error", "Cannot reach the server.")).mockResolvedValue(CLEAR);
    render(<VisitorDetail id="v1" />);
    expect(await screen.findByText("Cannot reach the server.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Hamza Tariq" })).toBeTruthy();
  });

  it("shows an empty visit history as such", async () => {
    api.visitorVisits.mockResolvedValue({ items: [], next_cursor: null });
    render(<VisitorDetail id="v1" />);
    expect(await screen.findByText("No visits yet.")).toBeTruthy();
  });

  it("offers editing only with the permission", async () => {
    session.canEdit = false;
    render(<VisitorDetail id="v1" />);
    await screen.findByRole("heading", { level: 1, name: "Hamza Tariq" });
    expect(screen.queryByRole("button", { name: "Edit details" })).toBeNull();
  });

  it("saves only what changed, confirms it and shows the new name", async () => {
    api.updateVisitor.mockResolvedValue({ ...VISITOR, full_name: "Hamza T. Khan" });
    render(<VisitorDetail id="v1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Edit details" }));
    // jsdom has no <dialog>.showModal(), so the modal's content counts as hidden.
    fireEvent.change(screen.getByLabelText("Full name"), { target: { value: "Hamza T. Khan" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes", hidden: true }));
    expect(await screen.findByRole("heading", { level: 1, name: "Hamza T. Khan" })).toBeTruthy();
    expect(api.updateVisitor).toHaveBeenCalledWith("v1", { full_name: "Hamza T. Khan" });
    expect(toastSuccess).toHaveBeenCalledWith("Visitor details updated.");
    await waitFor(() => expect(api.visitorVisits).toHaveBeenCalledTimes(2));   // history reloaded, as before
  });

  it("keeps the form open with the server's field error when saving fails", async () => {
    api.updateVisitor.mockRejectedValue(new ApiError(422, "validation_error", "Invalid", null,
      [{ field: "body.phone", message: "Enter a valid phone number." }]));
    render(<VisitorDetail id="v1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Edit details" }));
    fireEvent.change(screen.getByLabelText("Phone"), { target: { value: "0300 999 8888" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes", hidden: true }));
    expect(await screen.findByText("Enter a valid phone number.")).toBeTruthy();
    expect((screen.getByLabelText("Phone") as HTMLInputElement).value).toBe("0300 999 8888");
    expect(toastSuccess).not.toHaveBeenCalled();
  });

  it("rejects an invalid phone locally and normalises a valid international number", async () => {
    api.updateVisitor.mockResolvedValue({ ...VISITOR, phone: "+923001234567" });
    render(<VisitorDetail id="v1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Edit details" }));

    fireEvent.change(screen.getByLabelText("Phone"), { target: { value: "13001234567" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes", hidden: true }));
    expect(await screen.findByText(/valid Pakistani phone number/i)).toBeTruthy();
    expect(api.updateVisitor).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("Phone"), { target: { value: "+92 300 1234567" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes", hidden: true }));
    await waitFor(() => expect(api.updateVisitor).toHaveBeenCalledWith("v1", { phone: "+923001234567" }));
  });
});
