import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/client";
import type { Host } from "@/lib/api/directory";
import type { Visitor, VisitorWithStatus } from "@/lib/api/visitors";
import type { Visit } from "@/lib/api/visits";
import { installCamera } from "@/test-utils/camera";

const api = {
  lookupVisitor: vi.fn(), createVisitor: vi.fn(), getVisitor: vi.fn(), checkIn: vi.fn(), checkOut: vi.fn(),
  listHosts: vi.fn(), listDepartments: vi.fn(), issuePass: vi.fn(), recordBadgePrint: vi.fn(), uploadVisitorPhoto: vi.fn(),
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
vi.mock("@/lib/api/passes", async (original) => ({
  ...(await original<typeof import("@/lib/api/passes")>()),
  issuePass: (...a: unknown[]) => api.issuePass(...a),
  recordBadgePrint: (...a: unknown[]) => api.recordBadgePrint(...a),
}));
vi.mock("@/lib/api/photos", async (original) => ({
  ...(await original<typeof import("@/lib/api/photos")>()),
  uploadVisitorPhoto: (...a: unknown[]) => api.uploadVisitorPhoto(...a),
}));
vi.mock("@/lib/api/directory", () => ({
  listHosts: (...a: unknown[]) => api.listHosts(...a),
  listDepartments: (...a: unknown[]) => api.listDepartments(...a),
}));

const { CheckInWizard } = await import("./CheckInWizard");

const VISITOR: Visitor = {
  id: "v1", full_name: "Ali Khan", identity: { type: "CNIC", number: "35201-1234567-1" }, phone: null,
  created_at: "", updated_at: "", active_visit: null, photo_id: null,
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
  checkout_method: null, photo_id: null,
};

const ISSUED = {
  qr_text: `CGP1:${"A".repeat(64)}`, expires_at: "2026-09-28T08:00:00Z",
  badge: { organization: "Century Gate", visitor_name: "Ali Khan", visit_number: "V-2026-000042", host_name: "Sara Ahmed",
           department_name: "HR", gate_name: "Main Gate", check_in_at: "2026-09-27T08:00:00Z", valid_until: "2026-09-28T08:00:00Z" },
};

/** Visit details filled in and the photo step passed without a photo. */
async function detailsAndSkipPhoto() {
  fireEvent.click(await screen.findByRole("button", { name: /Sara Ahmed/ }));
  fireEvent.change(screen.getByLabelText("Reason for visit"), { target: { value: "INTERVIEW" } });
  fireEvent.click(screen.getByRole("button", { name: "Review" }));
  fireEvent.click(await screen.findByRole("button", { name: "Continue without a photo" }));
}

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  api.listHosts.mockResolvedValue([HOST]);
  api.listDepartments.mockResolvedValue([{ id: "d1", name: "HR", notification_email: null, is_active: true }]);
  api.issuePass.mockResolvedValue(ISSUED);
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
    await detailsAndSkipPhoto();
    fireEvent.click(await screen.findByRole("button", { name: "Confirm check-in" }));
    expect((await screen.findByTestId("visit-number")).textContent).toBe("V-2026-000042");
    expect(api.checkIn).toHaveBeenCalledWith(expect.objectContaining({
      visitor_id: "v1", host_id: "h1", department_id: "d1", reason_code: "INTERVIEW", photo_id: null }));
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
    await detailsAndSkipPhoto();
    fireEvent.click(await screen.findByRole("button", { name: "Confirm check-in" }));
    await waitFor(() => expect(screen.getByTestId("entry-denied")).toBeTruthy());
  });
});

describe("CheckInWizard photo, pass and badge", () => {
  async function toPhotoStep(found: VisitorWithStatus = CLEAR) {
    api.lookupVisitor.mockResolvedValue(found);
    findVisitor();
    fireEvent.click(await screen.findByRole("button", { name: /Sara Ahmed/ }));
    fireEvent.change(screen.getByLabelText("Reason for visit"), { target: { value: "INTERVIEW" } });
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await screen.findByText("Visitor photo");
  }

  it("captures and uploads a photo, and records it with the visit", async () => {
    const camera = installCamera();
    api.uploadVisitorPhoto.mockResolvedValue({ id: "p1", captured_at: "", width: 640, height: 480 });
    api.checkIn.mockResolvedValue({ ...VISIT, photo_id: "p1" });
    await toPhotoStep();
    fireEvent.click(screen.getByRole("button", { name: "Start camera" }));
    fireEvent.click(await screen.findByRole("button", { name: "Take photo" }));
    fireEvent.click(await screen.findByRole("button", { name: "Use this photo" }));
    await screen.findByRole("button", { name: "Confirm check-in" });
    expect(api.uploadVisitorPhoto).toHaveBeenCalledWith("v1", expect.any(Blob));
    expect(camera.tracks.every((t) => t.stopped)).toBe(true);                   // camera off before moving on
    expect(screen.getByTestId("visitor-photo").getAttribute("src")).toBe("/api/v1/photos/p1");
    fireEvent.click(screen.getByRole("button", { name: "Confirm check-in" }));
    await screen.findByTestId("visit-number");
    expect(api.checkIn).toHaveBeenCalledWith(expect.objectContaining({ photo_id: "p1" }));
  });

  it("offers to keep the photo from an earlier visit", async () => {
    installCamera();
    api.checkIn.mockResolvedValue(VISIT);
    await toPhotoStep({ ...CLEAR, visitor: { ...VISITOR, photo_id: "old" } });
    expect(screen.getByTestId("visitor-photo").getAttribute("src")).toBe("/api/v1/photos/old");
    fireEvent.click(screen.getByRole("button", { name: "Keep this photo" }));
    fireEvent.click(await screen.findByRole("button", { name: "Confirm check-in" }));
    await waitFor(() => expect(api.checkIn).toHaveBeenCalledWith(expect.objectContaining({ photo_id: "old" })));
    expect(api.uploadVisitorPhoto).not.toHaveBeenCalled();
  });

  it("issues the pass once and shows the badge to print", async () => {
    api.checkIn.mockResolvedValue(VISIT);
    await toPhotoStep();
    fireEvent.click(screen.getByRole("button", { name: "Continue without a photo" }));
    fireEvent.click(await screen.findByRole("button", { name: "Confirm check-in" }));
    expect((await screen.findByTestId("badge-name")).textContent).toBe("Ali Khan");
    expect(screen.getByRole("button", { name: "Print badge" })).toBeTruthy();
    expect(api.issuePass).toHaveBeenCalledTimes(1);
    expect(api.issuePass).toHaveBeenCalledWith("visit1");
  });

  it("keeps the visit and offers a retry when the pass cannot be issued", async () => {
    api.checkIn.mockResolvedValue(VISIT);
    api.issuePass.mockRejectedValueOnce(new ApiError(0, "network_error", "Cannot reach the server."));
    await toPhotoStep();
    fireEvent.click(screen.getByRole("button", { name: "Continue without a photo" }));
    fireEvent.click(await screen.findByRole("button", { name: "Confirm check-in" }));
    expect(await screen.findByText(/The pass could not be issued: Cannot reach the server\./)).toBeTruthy();
    expect(screen.getByTestId("visit-number").textContent).toBe("V-2026-000042");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByTestId("badge-card")).toBeTruthy();
  });
});
