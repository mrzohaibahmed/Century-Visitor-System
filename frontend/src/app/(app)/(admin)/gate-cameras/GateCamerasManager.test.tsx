import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/client";
import type { GateCamera } from "@/lib/api/gateCameras";

const api = { list: vi.fn(), save: vi.fn(), remove: vi.fn(), test: vi.fn(), photo: vi.fn() };
vi.mock("@/lib/api/gateCameras", async (original) => ({
  ...(await original<typeof import("@/lib/api/gateCameras")>()),
  listGateCameras: (...a: unknown[]) => api.list(...a),
  saveGateCamera: (...a: unknown[]) => api.save(...a),
  removeGateCamera: (...a: unknown[]) => api.remove(...a),
  testGateCamera: (...a: unknown[]) => api.test(...a),
  captureTestPhoto: (...a: unknown[]) => api.photo(...a),
}));
// The visitor-photo upload must never be used by this screen.
const uploadVisitorPhoto = vi.fn();
vi.mock("@/lib/api/photos", async (original) => ({
  ...(await original<typeof import("@/lib/api/photos")>()),
  uploadVisitorPhoto: (...a: unknown[]) => uploadVisitorPhoto(...a),
}));
const toast = { success: vi.fn() };
vi.mock("sonner", () => ({ toast: { success: (...a: unknown[]) => toast.success(...a) } }));

const { GateCamerasManager } = await import("./GateCamerasManager");

const SECRET = "Sup3r-Secret-Cam!";

const MAIN: GateCamera = {
  gate_id: "g1", gate_name: "Main Gate", gate_active: true, configured: true, enabled: true, host: "192.0.2.10",
  protocol: "https", port: null, channel: 101, username: "vms-snapshot", password_status: "SAVED", timeout_seconds: 5,
  updated_at: "2026-09-29T08:00:00Z",
  last_test: { tested_at: "2026-09-29T08:05:00Z", ok: true, code: null, message: null, model: "DS-2CD2143G2-I",
               firmware: "V5.7.15", device_name: "Main Gate Desk" },
};
const EAST: GateCamera = {
  gate_id: "g2", gate_name: "East Gate", gate_active: true, configured: false, enabled: false, host: null,
  protocol: null, port: null, channel: null, username: null, password_status: "NOT_SET", timeout_seconds: null,
  updated_at: null, last_test: null,
};
const NORTH: GateCamera = { ...MAIN, gate_id: "g3", gate_name: "North Gate", password_status: "UNREADABLE", last_test: null };

// jsdom has no <dialog>.showModal(), so a modal's content counts as hidden.
const inDialog = { hidden: true };
const consoleSpies: ReturnType<typeof vi.spyOn>[] = [];
const setItem = vi.spyOn(Storage.prototype, "setItem");

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  uploadVisitorPhoto.mockReset();
  toast.success.mockReset();
  setItem.mockClear();
  api.list.mockResolvedValue([MAIN, EAST, NORTH]);
  URL.createObjectURL = vi.fn(() => "blob:test-photo-1");
  URL.revokeObjectURL = vi.fn();
  for (const method of ["log", "info", "warn", "error", "debug"] as const) {
    consoleSpies.push(vi.spyOn(console, method).mockImplementation(() => {}));
  }
});
afterEach(() => {
  cleanup();
  consoleSpies.splice(0).forEach((s) => s.mockRestore());
  localStorage.clear();
  sessionStorage.clear();
});

function card(name: string): HTMLElement {
  return screen.getByRole("heading", { name }).closest("section")!;
}

async function openForm(gate: string, button: "Edit" | "Set up camera") {
  render(<GateCamerasManager />);
  await screen.findByRole("heading", { name: gate });
  fireEvent.click(within(card(gate)).getByRole("button", { name: button }));
}

function field(label: string) {
  return screen.getByLabelText(label) as HTMLInputElement;
}

function submitForm() {
  fireEvent.submit(field("Camera address").closest("form")!);
}

function deferred<T>() {
  let resolve!: (v: T) => void, reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

describe("GateCamerasManager: rendering", () => {
  it("shows a loading state, then one card per gate", async () => {
    const list = deferred<GateCamera[]>();
    api.list.mockReturnValue(list.promise);
    render(<GateCamerasManager />);
    expect(screen.getByText("Loading gate cameras…")).toBeTruthy();
    await act(async () => list.resolve([MAIN, EAST, NORTH]));
    for (const name of ["Main Gate", "East Gate", "North Gate"]) expect(screen.getByRole("heading", { name })).toBeTruthy();
    expect(api.test).not.toHaveBeenCalled();                          // never tested automatically
    expect(api.photo).not.toHaveBeenCalled();
  });

  it("shows a configured camera without its password", async () => {
    render(<GateCamerasManager />);
    const main = card(await screen.findByRole("heading", { name: "Main Gate" }).then(() => "Main Gate"));
    expect(main.textContent).toMatch(/Enabled.*HTTPS · 192\.0\.2\.10:443.*101.*vms-snapshot.*•••••••• \(saved\).*5 s/);
    const last = within(main).getByTestId("last-test");
    expect(last.textContent).toMatch(/Connected.*Model DS-2CD2143G2-I · Firmware V5\.7\.15/);
  });

  it("shows a gate without a camera as not set up", async () => {
    render(<GateCamerasManager />);
    await screen.findByRole("heading", { name: "East Gate" });
    const east = card("East Gate");
    expect(east.textContent).toContain("Not set up");
    expect(east.textContent).toContain("No camera is set up for this gate.");
    expect(within(east).getByRole("button", { name: "Set up camera" })).toBeTruthy();
    expect(within(east).queryByRole("button", { name: /Test connection/ })).toBeNull();
  });

  it("explains an unreadable password and does not offer tests with it", async () => {
    render(<GateCamerasManager />);
    await screen.findByRole("heading", { name: "North Gate" });
    const north = card("North Gate");
    expect(within(north).getByTestId("password-state").textContent).toBe("Saved, but cannot be read");
    expect(north.textContent).toContain("Edit the camera and enter the password again.");
    expect(within(north).getByTestId("last-test").textContent).toContain("Unreadable password");
    expect((within(north).getByRole("button", { name: "Test connection, North Gate" }) as HTMLButtonElement).disabled).toBe(true);
    expect((within(north).getByRole("button", { name: "Capture test photo, North Gate" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("shows a failed last test with its safe message", async () => {
    api.list.mockResolvedValue([{ ...MAIN, last_test: { ...MAIN.last_test!, ok: false, code: "CAMERA_TIMEOUT",
      message: "The camera did not answer in time.", model: null, firmware: null } }]);
    render(<GateCamerasManager />);
    const last = await screen.findByTestId("last-test");
    expect(last.textContent).toMatch(/Failed.*The camera did not answer in time\./);
    expect(last.textContent).not.toContain("CAMERA_TIMEOUT");
  });

  it("says what to do when there are no gates", async () => {
    api.list.mockResolvedValue([]);
    render(<GateCamerasManager />);
    expect(await screen.findByText("No gates yet")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Go to gates" }).getAttribute("href")).toBe("/directory/gates");
  });

  it("reports a failed load safely and can try again", async () => {
    api.list.mockRejectedValueOnce(new ApiError(0, "network_error", "Cannot reach the server. Check the network connection."));
    render(<GateCamerasManager />);
    expect(await screen.findByText("Cannot reach the server. Check the network connection.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("heading", { name: "Main Gate" })).toBeTruthy();
  });

  it("reports a refused load (403) with the API's message", async () => {
    api.list.mockRejectedValue(new ApiError(403, "forbidden", "You do not have permission to do this."));
    render(<GateCamerasManager />);
    expect(await screen.findByText("You do not have permission to do this.")).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Main Gate" })).toBeNull();
  });
});

describe("GateCamerasManager: saving", () => {
  it("sets up a camera with all fields and the password", async () => {
    api.save.mockResolvedValue({ ...EAST, configured: true, password_status: "SAVED" });
    await openForm("East Gate", "Set up camera");
    fireEvent.change(field("Camera address"), { target: { value: " 192.0.2.20 " } });
    fireEvent.change(field("Connection"), { target: { value: "http" } });
    fireEvent.change(field("Port"), { target: { value: "8080" } });
    fireEvent.change(field("Channel"), { target: { value: "201" } });
    fireEvent.change(field("Camera user name"), { target: { value: "vms-snapshot" } });
    fireEvent.change(field("Camera password"), { target: { value: SECRET } });
    submitForm();
    await waitFor(() => expect(api.save).toHaveBeenCalledWith("g2", {
      enabled: true, host: "192.0.2.20", protocol: "http", port: 8080, channel: 201, username: "vms-snapshot",
      timeout_seconds: 5, password: SECRET,
    }));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Camera settings saved for EAST GATE."));
    expect(api.list).toHaveBeenCalledTimes(2);                        // refreshed
  });

  it("keeps the saved password: it is not prefilled and not sent", async () => {
    api.save.mockResolvedValue({ ...MAIN, channel: 102 });
    await openForm("Main Gate", "Edit");
    const password = field("Camera password");
    expect(password.value).toBe("");
    expect(password.type).toBe("password");
    fireEvent.change(field("Channel"), { target: { value: "102" } });
    submitForm();
    await waitFor(() => expect(api.save).toHaveBeenCalled());
    const [, input] = api.save.mock.calls[0];
    expect(input).toEqual({ enabled: true, host: "192.0.2.10", protocol: "https", port: null, channel: 102,
                            username: "vms-snapshot", timeout_seconds: 5 });
    expect("password" in input).toBe(false);
  });

  it("asks for the password again when the address changes", async () => {
    await openForm("Main Gate", "Edit");
    fireEvent.change(field("Camera address"), { target: { value: "192.0.2.99" } });
    expect(screen.getByText("Required again: you changed the address, connection, port or user name.")).toBeTruthy();
    submitForm();
    expect(await screen.findByText("You changed the address, connection, port or user name: enter the camera password again.")).toBeTruthy();
    expect(api.save).not.toHaveBeenCalled();
    api.save.mockResolvedValue(MAIN);
    fireEvent.change(field("Camera password"), { target: { value: SECRET } });
    submitForm();
    await waitFor(() => expect(api.save.mock.calls[0][1]).toMatchObject({ host: "192.0.2.99", password: SECRET }));
  });

  it("shows the server's password-required answer on the password field", async () => {
    api.save.mockRejectedValue(new ApiError(422, "camera_password_required",
      "Enter the camera password again when changing the address, connection, port or user name."));
    await openForm("Main Gate", "Edit");
    fireEvent.change(field("Timeout (seconds)"), { target: { value: "8" } });
    submitForm();
    expect(await screen.findByText(/Enter the camera password again when changing/)).toBeTruthy();
    expect(field("Camera password").getAttribute("aria-invalid")).toBe("true");
  });

  it("shows validation problems per field without echoing the values", async () => {
    api.save.mockRejectedValue(new ApiError(422, "validation_error", "The request is not valid.",
      null, [{ field: "body.port", message: "Input should be less than or equal to 65535" }]));
    await openForm("East Gate", "Set up camera");
    fireEvent.change(field("Camera address"), { target: { value: "192.0.2.20" } });
    fireEvent.change(field("Camera user name"), { target: { value: "vms" } });
    fireEvent.change(field("Camera password"), { target: { value: SECRET } });
    submitForm();
    expect(await screen.findByText("Input should be less than or equal to 65535")).toBeTruthy();
    expect(document.body.textContent).not.toContain(SECRET);
  });

  it("checks the obvious mistakes before sending", async () => {
    await openForm("East Gate", "Set up camera");
    fireEvent.change(field("Port"), { target: { value: "99999" } });
    fireEvent.change(field("Channel"), { target: { value: "abc" } });
    fireEvent.change(field("Timeout (seconds)"), { target: { value: "60" } });
    submitForm();
    for (const text of ["Enter the camera's IP address or host name.", "The port is a number from 1 to 65535.",
      "The channel is a number from 1 to 65535.", "Enter the camera user name.", "The timeout is 1 to 30 seconds.",
      "Enter the camera password."]) {
      expect(await screen.findByText(text)).toBeTruthy();
    }
    expect(api.save).not.toHaveBeenCalled();
  });

  it("reports a server without CG_SECRETS_KEY", async () => {
    api.save.mockRejectedValue(new ApiError(503, "secrets_key_missing",
      "Camera passwords cannot be used: the server has no CG_SECRETS_KEY. Ask the administrator."));
    await openForm("East Gate", "Set up camera");
    fireEvent.change(field("Camera address"), { target: { value: "192.0.2.20" } });
    fireEvent.change(field("Camera user name"), { target: { value: "vms" } });
    fireEvent.change(field("Camera password"), { target: { value: SECRET } });
    submitForm();
    expect(await screen.findByText(/the server has no CG_SECRETS_KEY/)).toBeTruthy();
  });
});

describe("GateCamerasManager: removing", () => {
  it("asks first, and Cancel removes nothing", async () => {
    render(<GateCamerasManager />);
    await screen.findByRole("heading", { name: "Main Gate" });
    fireEvent.click(within(card("Main Gate")).getByRole("button", { name: "Remove" }));
    expect(screen.getByText(/including the saved camera password,\s+will be deleted/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Cancel", ...inDialog }));
    expect(api.remove).not.toHaveBeenCalled();
  });

  it("removes after confirmation and refreshes the cards", async () => {
    api.remove.mockResolvedValue(undefined);
    render(<GateCamerasManager />);
    await screen.findByRole("heading", { name: "Main Gate" });
    api.list.mockResolvedValue([{ ...EAST, gate_id: "g1", gate_name: "Main Gate" }, EAST, NORTH]);
    fireEvent.click(within(card("Main Gate")).getByRole("button", { name: "Remove" }));
    fireEvent.click(screen.getByRole("button", { name: "Remove camera", ...inDialog }));
    await waitFor(() => expect(api.remove).toHaveBeenCalledWith("g1"));
    await waitFor(() => expect(card("Main Gate").textContent).toContain("Not set up"));
    expect(toast.success).toHaveBeenCalledWith("Camera removed from MAIN GATE.");
  });
});

describe("GateCamerasManager: test connection", () => {
  it("shows progress, allows one request at a time, then shows the saved result", async () => {
    const pending = deferred<unknown>();
    api.test.mockReturnValue(pending.promise);
    render(<GateCamerasManager />);
    await screen.findByRole("heading", { name: "Main Gate" });
    const button = within(card("Main Gate")).getByRole("button", { name: "Test connection, Main Gate" });
    fireEvent.click(button);
    fireEvent.click(button);                                          // double click
    expect(api.test).toHaveBeenCalledTimes(1);
    expect(api.test).toHaveBeenCalledWith("g1");
    expect(screen.getByText("Testing the camera…")).toBeTruthy();
    expect((button as HTMLButtonElement).disabled).toBe(true);
    api.list.mockResolvedValue([{ ...MAIN, last_test: { ...MAIN.last_test!, model: "DS-2CD2387G2" } }, EAST, NORTH]);
    await act(async () => pending.resolve({ status: "CONNECTED" }));
    await waitFor(() => expect(within(card("Main Gate")).getByTestId("last-test").textContent).toContain("DS-2CD2387G2"));
    expect(screen.queryByText("Testing the camera…")).toBeNull();
  });

  it("shows a failure with the API's safe message only", async () => {
    api.test.mockRejectedValue(new ApiError(409, "camera_password_unreadable",
      "The saved camera password cannot be read (the server key has changed). Enter the camera password again."));
    render(<GateCamerasManager />);
    await screen.findByRole("heading", { name: "Main Gate" });
    fireEvent.click(within(card("Main Gate")).getByRole("button", { name: "Test connection, Main Gate" }));
    expect(await within(card("Main Gate")).findByText(/cannot be read \(the server key has changed\)/)).toBeTruthy();
    expect(card("Main Gate").textContent).not.toContain("camera_password_unreadable");
  });

  it("shows a network failure safely", async () => {
    api.test.mockRejectedValue(new ApiError(0, "network_error", "Cannot reach the server. Check the network connection."));
    render(<GateCamerasManager />);
    await screen.findByRole("heading", { name: "Main Gate" });
    fireEvent.click(within(card("Main Gate")).getByRole("button", { name: "Test connection, Main Gate" }));
    expect(await within(card("Main Gate")).findByText("Cannot reach the server. Check the network connection.")).toBeTruthy();
  });
});

describe("GateCamerasManager: test photo", () => {
  it("shows the picture, labelled as not stored, and forgets it on close", async () => {
    const pending = deferred<unknown>();
    api.photo.mockReturnValue(pending.promise);
    render(<GateCamerasManager />);
    await screen.findByRole("heading", { name: "Main Gate" });
    const button = within(card("Main Gate")).getByRole("button", { name: "Capture test photo, Main Gate" });
    fireEvent.click(button);
    fireEvent.click(button);
    expect(api.photo).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Taking a test photo…")).toBeTruthy();
    const blob = new Blob([new Uint8Array([0xff, 0xd8, 0xff])], { type: "image/jpeg" });
    await act(async () => pending.resolve({ blob, cameraSize: [2560, 1440], photoSize: [1024, 576] }));

    const img = screen.getByTestId("test-photo") as HTMLImageElement;
    expect(img.getAttribute("src")).toBe("blob:test-photo-1");
    expect(img.alt).toBe("Test photo from the MAIN GATE camera (not stored)");
    expect(screen.getByTestId("test-photo-label").textContent).toBe("TEST PHOTO — NOT STORED");
    expect(screen.getByText(/Camera picture 2560 × 1440 px\. A visitor photo from this camera is kept at 1024 × 576 px\./))
      .toBeTruthy();

    fireEvent.click(screen.getAllByRole("button", { name: "Close", ...inDialog }).at(-1)!);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:test-photo-1");
    expect(screen.queryByTestId("test-photo")).toBeNull();
    expect(uploadVisitorPhoto).not.toHaveBeenCalled();               // never becomes a visitor photo
    expect(setItem).not.toHaveBeenCalled();                          // never kept in the browser
  });

  it("reports a camera failure with the API's safe message", async () => {
    api.photo.mockRejectedValue(new ApiError(502, "camera_not_found",
      "The camera has no picture on this channel. Check the channel number."));
    render(<GateCamerasManager />);
    await screen.findByRole("heading", { name: "Main Gate" });
    fireEvent.click(within(card("Main Gate")).getByRole("button", { name: "Capture test photo, Main Gate" }));
    expect(await screen.findByText("The camera has no picture on this channel. Check the channel number.")).toBeTruthy();
    expect(screen.queryByTestId("test-photo")).toBeNull();
  });
});

describe("GateCamerasManager: the password never leaks", () => {
  it("is not rendered, stored, put in the URL or logged, and only sent with Save", async () => {
    api.save.mockRejectedValueOnce(new ApiError(502, "http_error", "Something went wrong. Please try again."));
    api.save.mockResolvedValue({ ...MAIN, host: "192.0.2.99" });
    api.test.mockResolvedValue({ status: "CONNECTED" });
    await openForm("Main Gate", "Edit");
    fireEvent.change(field("Camera address"), { target: { value: "192.0.2.99" } });
    fireEvent.change(field("Camera password"), { target: { value: SECRET } });
    submitForm();                                                     // fails first
    expect(await screen.findByText("Something went wrong. Please try again.")).toBeTruthy();
    expect(document.body.textContent).not.toContain(SECRET);
    submitForm();                                                     // then saves
    await waitFor(() => expect(toast.success).toHaveBeenCalled());
    fireEvent.click(within(card("Main Gate")).getByRole("button", { name: "Test connection, Main Gate" }));
    await waitFor(() => expect(api.test).toHaveBeenCalled());

    expect(document.documentElement.outerHTML).not.toContain(SECRET);  // form closed: nowhere on the page
    expect(window.location.href).not.toContain(SECRET);
    expect(setItem).not.toHaveBeenCalled();
    expect(localStorage.length + sessionStorage.length).toBe(0);
    for (const spy of consoleSpies) expect(JSON.stringify(spy.mock.calls)).not.toContain(SECRET);
    expect(JSON.stringify([api.list.mock.calls, api.test.mock.calls, api.photo.mock.calls, api.remove.mock.calls]))
      .not.toContain(SECRET);                                         // only Save carries it
    expect(api.save.mock.calls.every(([, input]) => input.password === SECRET)).toBe(true);
  });
});
