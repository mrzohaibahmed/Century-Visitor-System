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
  sessionGateCamera: vi.fn(), captureGateCameraPhoto: vi.fn(), gateCameraPreviewFrame: vi.fn(),
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
vi.mock("@/lib/api/gateCameras", async (original) => ({
  ...(await original<typeof import("@/lib/api/gateCameras")>()),
  sessionGateCamera: (...a: unknown[]) => api.sessionGateCamera(...a),
  captureGateCameraPhoto: (...a: unknown[]) => api.captureGateCameraPhoto(...a),
  gateCameraPreviewFrame: (...a: unknown[]) => api.gateCameraPreviewFrame(...a),
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
  id: "h1", name: "Sara Ahmed", email: null, phone: null, department_id: "d1", department_name: "HR", is_active: true, linked_user: null,
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
  api.sessionGateCamera.mockResolvedValue({ available: false });          // no gate camera: the webcam, as before
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

  it("looks the visitor up by the ID type tapped", async () => {
    api.lookupVisitor.mockRejectedValue(new ApiError(404, "not_found", "No visitor is registered with this ID number."));
    render(<CheckInWizard />);
    fireEvent.click(screen.getByRole("radio", { name: "Passport" }));
    fireEvent.change(screen.getByLabelText("ID number"), { target: { value: "AB1234567" } });
    fireEvent.click(screen.getByRole("button", { name: "Find visitor" }));
    await waitFor(() => expect(api.lookupVisitor).toHaveBeenCalledWith("PASSPORT", "AB1234567"));
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

  it("makes entry denied a hard stop that is announced and resets on Done", async () => {
    api.lookupVisitor.mockResolvedValue({ ...CLEAR, screening: { status: "BLOCKED", reason: "Theft." } });
    findVisitor();
    const denied = await screen.findByRole("alert");
    expect(denied.getAttribute("data-testid")).toBe("entry-denied");
    expect(document.activeElement).toBe(screen.getByRole("heading", { name: "Entry not permitted" }));
    expect(screen.queryByRole("button", { name: /Review|Confirm/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect((screen.getByLabelText("ID number") as HTMLInputElement).value).toBe("");
  });

  it("moves focus to the new step's heading", async () => {
    api.lookupVisitor.mockResolvedValue(CLEAR);
    findVisitor();
    const heading = await screen.findByRole("heading", { name: "Visit details" });
    expect(document.activeElement).toBe(heading);
  });

  it("checks out the earlier visit of a visitor still inside, and reports a failure without moving on", async () => {
    api.lookupVisitor.mockResolvedValue({ ...CLEAR, visitor: { ...VISITOR, active_visit: {
      id: "old", visit_number: "V-2026-000001", check_in_at: "2026-09-27T07:00:00Z", gate_name: "Main Gate" } } });
    api.checkOut.mockRejectedValueOnce(new ApiError(0, "network_error", "Cannot reach the server.")).mockResolvedValue({});
    findVisitor();
    const checkOutFirst = await screen.findByRole("button", { name: "Check out previous visit and continue" });
    fireEvent.click(checkOutFirst);
    expect(await screen.findByText("The previous visit was not checked out")).toBeTruthy();
    expect(screen.getByText("Already inside")).toBeTruthy();
    fireEvent.click(checkOutFirst);
    expect(await screen.findByRole("heading", { name: "Visit details" })).toBeTruthy();
    expect(api.checkOut).toHaveBeenLastCalledWith("old");
  });

  it("cannot cancel an already-inside visitor while the previous visit is being checked out", async () => {
    api.lookupVisitor.mockResolvedValue({ ...CLEAR, visitor: { ...VISITOR, active_visit: {
      id: "old", visit_number: "V-2026-000001", check_in_at: "2026-09-27T07:00:00Z", gate_name: "Main Gate" } } });
    api.checkOut.mockReturnValue(new Promise(() => {}));
    findVisitor();
    fireEvent.click(await screen.findByRole("button", { name: "Check out previous visit and continue" }));
    expect((screen.getByRole("button", { name: "Cancel" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("cannot go back from registration while the visitor is being registered", async () => {
    api.lookupVisitor.mockRejectedValue(new ApiError(404, "not_found", "No visitor is registered with this ID number."));
    api.createVisitor.mockReturnValue(new Promise(() => {}));
    findVisitor();
    fireEvent.change(await screen.findByLabelText("Full name"), { target: { value: "Ali Khan" } });
    fireEvent.click(screen.getByRole("button", { name: "Register and continue" }));
    expect((screen.getByRole("button", { name: "Back" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("rejects an invalid phone on the new-visitor form before calling the API", async () => {
    api.lookupVisitor.mockRejectedValue(new ApiError(404, "not_found", "No visitor is registered with this ID number."));
    findVisitor();
    fireEvent.change(await screen.findByLabelText("Full name"), { target: { value: "Ali Khan" } });
    fireEvent.change(screen.getByLabelText("Phone (optional)"), { target: { value: "123" } });
    fireEvent.click(screen.getByRole("button", { name: "Register and continue" }));
    expect(await screen.findByText("Enter a valid phone number (11 digits).")).toBeTruthy();
    expect(api.createVisitor).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Phone (optional)"), { target: { value: "0300-1234567" } });
    expect(screen.queryByText("Enter a valid phone number (11 digits).")).toBeNull();
    api.createVisitor.mockResolvedValue({ id: "v1" });
    api.getVisitor.mockResolvedValue(CLEAR);
    fireEvent.click(screen.getByRole("button", { name: "Register and continue" }));
    await waitFor(() => expect(api.createVisitor).toHaveBeenCalledWith(expect.objectContaining({
      phone: "03001234567",
    })));
  });

  it("titles a lookup failure and keeps the ID number for another try", async () => {
    api.lookupVisitor.mockRejectedValueOnce(new ApiError(0, "network_error", "Cannot reach the server.")).mockResolvedValue(CLEAR);
    findVisitor();
    expect(await screen.findByText("The visitor could not be looked up")).toBeTruthy();
    expect((screen.getByLabelText("ID number") as HTMLInputElement).value).not.toBe("");
    fireEvent.click(screen.getByRole("button", { name: "Find visitor" }));
    expect(await screen.findByRole("heading", { name: "Visit details" })).toBeTruthy();
  });

  it("says when the departments cannot be loaded, and loads them again on request", async () => {
    api.lookupVisitor.mockResolvedValue(CLEAR);
    api.listDepartments.mockRejectedValueOnce(new ApiError(0, "network_error", "Cannot reach the server."));
    findVisitor();
    expect(await screen.findByText("The list of departments could not be loaded.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Load again" }));
    await waitFor(() => expect(screen.queryByText("The list of departments could not be loaded.")).toBeNull());
    expect(screen.getByRole("option", { name: "HR" })).toBeTruthy();
  });

  it("keeps keyboard focus in the host picker when a host is chosen or changed", async () => {
    api.lookupVisitor.mockResolvedValue(CLEAR);
    findVisitor();
    fireEvent.click(await screen.findByRole("button", { name: /Sara Ahmed/ }));
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Change" }));
    fireEvent.click(screen.getByRole("button", { name: "Change" }));
    expect(document.activeElement).toBe(screen.getByLabelText("Host (person being visited)"));
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

  it("clears an error as soon as its field is corrected, and adds none before Review", async () => {
    api.lookupVisitor.mockResolvedValue(CLEAR);
    findVisitor();
    expect(screen.queryByText("Choose the person being visited.")).toBeNull();           // nothing new before Review
    fireEvent.click(await screen.findByRole("button", { name: "Review" }));
    expect(screen.getByText("Choose the person being visited.")).toBeTruthy();
    expect(screen.getByText("Choose the department being visited.")).toBeTruthy();
    fireEvent.click(await screen.findByRole("button", { name: /Sara Ahmed/ }));
    expect(screen.queryByText("Choose the person being visited.")).toBeNull();
    expect(screen.queryByText("Choose the department being visited.")).toBeNull();       // taken from the host
    expect(screen.getByText("Choose the reason for the visit.")).toBeTruthy();         // still wrong: still shown
    fireEvent.change(screen.getByLabelText("Reason for visit"), { target: { value: "INTERVIEW" } });
    expect(screen.queryByText("Choose the reason for the visit.")).toBeNull();
  });

  it("opens the personal material returnable form from belongings", async () => {
    api.lookupVisitor.mockResolvedValue(CLEAR);
    findVisitor();
    fireEvent.click(await screen.findByRole("button", { name: /Add personal material/i }));
    expect(await screen.findByRole("heading", { name: "Personal Material Returnable", hidden: true })).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Description 1"), { target: { value: "Laptop" } });
    fireEvent.change(screen.getByLabelText("Quantity in 1"), { target: { value: "01" } });
    fireEvent.click(screen.getByRole("button", { name: "Save belongings", hidden: true }));
    expect(await screen.findByText("Laptop")).toBeTruthy();
  });

  it("goes back from review to edit the visit details without losing them", async () => {
    api.lookupVisitor.mockResolvedValue(CLEAR);
    api.checkIn.mockResolvedValue(VISIT);
    findVisitor();
    await detailsAndSkipPhoto();
    expect(screen.queryByText("Also recorded")).toBeNull();                 // no vehicle or belongings entered
    fireEvent.click(await screen.findByRole("button", { name: "Edit visit details" }));
    expect((await screen.findByTestId("selected-host")).textContent).toBe("Sara Ahmed");
    expect((screen.getByLabelText("Reason for visit") as HTMLSelectElement).value).toBe("INTERVIEW");
    fireEvent.change(screen.getByLabelText("Vehicle registration (optional)"), { target: { value: "lea-1234" } });
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    fireEvent.click(await screen.findByRole("button", { name: "Continue without a photo" }));
    expect(await screen.findByText("LEA-1234")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Confirm check-in" }));
    await screen.findByTestId("visit-number");
    expect(api.checkIn).toHaveBeenCalledWith(expect.objectContaining({
      host_id: "h1", department_id: "d1", reason_code: "INTERVIEW", vehicle_registration: "lea-1234", photo_id: null }));
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
    await waitFor(() => expect(screen.queryByText("Checking for a gate camera…")).toBeNull());
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

  it("holds Back and Continue without a photo while the photo is saving", async () => {
    installCamera();
    api.uploadVisitorPhoto.mockReturnValue(new Promise(() => {}));
    await toPhotoStep();
    fireEvent.click(screen.getByRole("button", { name: "Start camera" }));
    fireEvent.click(await screen.findByRole("button", { name: "Take photo" }));
    fireEvent.click(await screen.findByRole("button", { name: "Use this photo" }));
    await waitFor(() => expect((screen.getByRole("button", { name: "Back" }) as HTMLButtonElement).disabled).toBe(true));
    expect((screen.getByRole("button", { name: "Continue without a photo" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("offers the photo just taken again after editing the details from review", async () => {
    installCamera();
    api.uploadVisitorPhoto.mockResolvedValue({ id: "p1", captured_at: "", width: 640, height: 480 });
    api.checkIn.mockResolvedValue({ ...VISIT, photo_id: "p1" });
    await toPhotoStep();
    fireEvent.click(screen.getByRole("button", { name: "Start camera" }));
    fireEvent.click(await screen.findByRole("button", { name: "Take photo" }));
    fireEvent.click(await screen.findByRole("button", { name: "Use this photo" }));
    fireEvent.click(await screen.findByRole("button", { name: "Edit visit details" }));
    fireEvent.click(await screen.findByRole("button", { name: "Review" }));
    expect(await screen.findByText("Photo captured for this visit.")).toBeTruthy();
    expect(screen.queryByText(/Photo from an earlier visit/)).toBeNull();
    fireEvent.click(await screen.findByRole("button", { name: "Keep this photo" }));
    fireEvent.click(await screen.findByRole("button", { name: "Confirm check-in" }));
    await waitFor(() => expect(api.checkIn).toHaveBeenCalledWith(expect.objectContaining({ photo_id: "p1" })));
    expect(api.uploadVisitorPhoto).toHaveBeenCalledTimes(1);
  });

  it("offers the photo just taken again when going back from review, without a second upload", async () => {
    installCamera();
    api.uploadVisitorPhoto.mockResolvedValue({ id: "p1", captured_at: "", width: 640, height: 480 });
    api.checkIn.mockResolvedValue({ ...VISIT, photo_id: "p1" });
    await toPhotoStep();
    fireEvent.click(screen.getByRole("button", { name: "Start camera" }));
    fireEvent.click(await screen.findByRole("button", { name: "Take photo" }));
    fireEvent.click(await screen.findByRole("button", { name: "Use this photo" }));
    await screen.findByRole("button", { name: "Confirm check-in" });                 // on review now
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(await screen.findByText("Photo captured for this visit.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Keep this photo" }));
    fireEvent.click(await screen.findByRole("button", { name: "Confirm check-in" }));
    await waitFor(() => expect(api.checkIn).toHaveBeenCalledWith(expect.objectContaining({ photo_id: "p1" })));
    expect(api.uploadVisitorPhoto).toHaveBeenCalledTimes(1);
  });

  it("offers to keep the photo from an earlier visit", async () => {
    installCamera();
    api.checkIn.mockResolvedValue(VISIT);
    await toPhotoStep({ ...CLEAR, visitor: { ...VISITOR, photo_id: "old" } });
    expect(screen.getByTestId("visitor-photo").getAttribute("src")).toBe("/api/v1/photos/old");
    expect(screen.getByText(/Photo from an earlier visit/)).toBeTruthy();
    expect(screen.queryByText("Photo captured for this visit.")).toBeNull();
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

  it("confirms the check-in, then starts the next visitor from a clean slate", async () => {
    api.checkIn.mockResolvedValue(VISIT);
    await toPhotoStep();
    fireEvent.click(screen.getByRole("button", { name: "Continue without a photo" }));
    fireEvent.click(await screen.findByRole("button", { name: "Confirm check-in" }));
    expect(await screen.findByRole("heading", { name: "Check-in complete" })).toBeTruthy();
    expect(await screen.findByRole("button", { name: "Print badge" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Visitors inside" }).getAttribute("href")).toBe("/check-out");
    fireEvent.click(screen.getByRole("button", { name: "Check in next visitor" }));
    expect((screen.getByLabelText("ID number") as HTMLInputElement).value).toBe("");
    expect(screen.queryByTestId("check-in-done")).toBeNull();
    // The next visitor's details start empty (no host or reason carried over).
    api.lookupVisitor.mockResolvedValue({ ...CLEAR, visitor: { ...VISITOR, id: "v2", full_name: "Hina Shah" } });
    fireEvent.change(screen.getByLabelText("ID number"), { target: { value: "3520199999999" } });
    fireEvent.click(screen.getByRole("button", { name: "Find visitor" }));
    expect((await screen.findByTestId("visitor-name")).textContent).toBe("Hina Shah");
    expect(screen.queryByTestId("selected-host")).toBeNull();
    expect((screen.getByLabelText("Reason for visit") as HTMLSelectElement).value).toBe("");
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

describe("CheckInWizard photo from the gate camera", () => {
  async function toPhotoStep(found: VisitorWithStatus = CLEAR) {
    api.lookupVisitor.mockResolvedValue(found);
    findVisitor();
    fireEvent.click(await screen.findByRole("button", { name: /Sara Ahmed/ }));
    fireEvent.change(screen.getByLabelText("Reason for visit"), { target: { value: "INTERVIEW" } });
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await screen.findByText("Visitor photo");
  }
  const picture = new Blob([new Uint8Array([0xff, 0xd8, 0xff, 0xe0])], { type: "image/jpeg" });

  beforeEach(() => {
    api.sessionGateCamera.mockResolvedValue({ available: true });
    api.gateCameraPreviewFrame.mockResolvedValue(picture);                   // live view
    URL.createObjectURL = vi.fn(() => "blob:gate-1");
    URL.revokeObjectURL = vi.fn();
  });

  it("offers the gate camera first; its photo goes through the normal upload into the check-in", async () => {
    api.captureGateCameraPhoto.mockResolvedValue(picture);
    api.uploadVisitorPhoto.mockResolvedValue({ id: "p1", captured_at: "", width: 1024, height: 576 });
    api.checkIn.mockResolvedValue({ ...VISIT, photo_id: "p1" });
    await toPhotoStep();
    expect(api.sessionGateCamera).toHaveBeenCalledWith();                     // the server picks the camera
    fireEvent.click(await screen.findByRole("button", { name: "Take photo with gate camera" }));
    expect((await screen.findByTestId("gate-camera-photo")).getAttribute("src")).toBe("blob:gate-1");
    expect(api.captureGateCameraPhoto).toHaveBeenCalledWith();
    expect(api.uploadVisitorPhoto).not.toHaveBeenCalled();                    // a preview is not a visitor photo
    fireEvent.click(screen.getByRole("button", { name: "Use this photo" }));
    await screen.findByRole("button", { name: "Confirm check-in" });
    expect(api.uploadVisitorPhoto).toHaveBeenCalledWith("v1", picture);       // same upload as the webcam
    expect(api.uploadVisitorPhoto).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Confirm check-in" }));
    await screen.findByTestId("visit-number");
    expect(api.checkIn).toHaveBeenCalledWith(expect.objectContaining({ photo_id: "p1" }));
  });

  it("Retake takes a new picture without uploading anything", async () => {
    api.captureGateCameraPhoto.mockResolvedValue(picture);
    await toPhotoStep();
    fireEvent.click(await screen.findByRole("button", { name: "Take photo with gate camera" }));
    fireEvent.click(await screen.findByRole("button", { name: "Retake" }));
    fireEvent.click(await screen.findByRole("button", { name: "Take photo with gate camera" }));
    await screen.findByRole("button", { name: "Use this photo" });
    expect(api.captureGateCameraPhoto).toHaveBeenCalledTimes(2);
    expect(api.uploadVisitorPhoto).not.toHaveBeenCalled();
  });

  it("a failed gate camera never blocks the check-in: the webcam is one click away", async () => {
    const camera = installCamera();
    api.captureGateCameraPhoto.mockRejectedValue(new ApiError(502, "camera_timeout", "The camera did not answer in time."));
    api.uploadVisitorPhoto.mockResolvedValue({ id: "p2", captured_at: "", width: 640, height: 480 });
    await toPhotoStep();
    fireEvent.click(await screen.findByRole("button", { name: "Take photo with gate camera" }));
    expect((await screen.findByRole("alert")).textContent).toContain("The camera did not answer in time.");
    fireEvent.click(screen.getByRole("button", { name: "Use webcam" }));
    fireEvent.click(screen.getByRole("button", { name: "Start camera" }));
    fireEvent.click(await screen.findByRole("button", { name: "Take photo" }));
    fireEvent.click(await screen.findByRole("button", { name: "Use this photo" }));
    await screen.findByRole("button", { name: "Confirm check-in" });
    expect(api.uploadVisitorPhoto).toHaveBeenCalledWith("v1", expect.any(Blob));
    expect(camera.tracks.every((t) => t.stopped)).toBe(true);
  });

  it("can switch to the webcam and back without asking the camera", async () => {
    installCamera();
    await toPhotoStep();
    fireEvent.click(await screen.findByRole("button", { name: "Use webcam" }));
    expect(screen.getByRole("button", { name: "Start camera" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Use the gate camera instead" }));
    expect(screen.getByRole("button", { name: "Take photo with gate camera" })).toBeTruthy();
    expect(api.captureGateCameraPhoto).not.toHaveBeenCalled();
  });

  it("continue without a photo still works with a gate camera", async () => {
    api.checkIn.mockResolvedValue(VISIT);
    await toPhotoStep();
    await screen.findByRole("button", { name: "Take photo with gate camera" });
    fireEvent.click(screen.getByRole("button", { name: "Continue without a photo" }));
    fireEvent.click(await screen.findByRole("button", { name: "Confirm check-in" }));
    await screen.findByTestId("visit-number");
    expect(api.checkIn).toHaveBeenCalledWith(expect.objectContaining({ photo_id: null }));
    expect(api.captureGateCameraPhoto).not.toHaveBeenCalled();
    expect(api.uploadVisitorPhoto).not.toHaveBeenCalled();
  });

  it.each([
    ["no usable camera (none, disabled or unreadable)", () => api.sessionGateCamera.mockResolvedValue({ available: false })],
    ["a refused check (403)", () => api.sessionGateCamera.mockRejectedValue(new ApiError(403, "forbidden", "No."))],
    ["a network failure", () => api.sessionGateCamera.mockRejectedValue(new ApiError(0, "network_error", "Offline."))],
  ])("with %s, the webcam is used exactly as before", async (_, setup) => {
    setup();
    await toPhotoStep();
    expect(await screen.findByRole("button", { name: "Start camera" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /gate camera/ })).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();                          // no broken camera UI
    expect(api.captureGateCameraPhoto).not.toHaveBeenCalled();
  });
});
