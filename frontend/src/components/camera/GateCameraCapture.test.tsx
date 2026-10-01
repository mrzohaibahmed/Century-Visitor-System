import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/client";

const api = { capture: vi.fn(), preview: vi.fn() };
vi.mock("@/lib/api/gateCameras", async (original) => ({
  ...(await original<typeof import("@/lib/api/gateCameras")>()),
  captureGateCameraPhoto: (...a: unknown[]) => api.capture(...a),
  gateCameraPreviewFrame: (...a: unknown[]) => api.preview(...a),
}));

const { GateCameraCapture } = await import("./GateCameraCapture");

const picture = (n: number) => new Blob([new Uint8Array([0xff, 0xd8, 0xff, n])], { type: "image/jpeg" });
const liveFrame = picture(0);
let urls = 0;
let frames = 0;
const setItem = vi.spyOn(Storage.prototype, "setItem");

beforeEach(() => {
  api.capture.mockReset();
  api.preview.mockReset();
  api.preview.mockResolvedValue(liveFrame);
  setItem.mockClear();
  urls = 0;
  frames = 0;
  URL.createObjectURL = vi.fn((blob: Blob) => (blob === liveFrame ? `blob:frame-${++frames}` : `blob:gate-${++urls}`));
  URL.revokeObjectURL = vi.fn();
});
afterEach(cleanup);

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

function setup(onConfirm = vi.fn().mockResolvedValue(undefined)) {
  const onUseWebcam = vi.fn();
  render(<GateCameraCapture onConfirm={onConfirm} onUseWebcam={onUseWebcam} />);
  return { onConfirm, onUseWebcam };
}

const takeButton = () => screen.getByRole("button", { name: "Take photo with gate camera" });

describe("GateCameraCapture", () => {
  it("shows a live view from the gate camera, frame after frame, without naming the camera", async () => {
    setup();
    expect((await screen.findByTestId("gate-camera-live")).getAttribute("src")).toMatch(/^blob:frame-/);
    expect(screen.getByText("Live")).toBeTruthy();
    expect(screen.getByTestId("gate-camera-guide")).toBeTruthy();              // face guide, as on the webcam
    await vi.waitFor(() => expect(api.preview.mock.calls.length).toBeGreaterThan(1));
    expect(api.preview.mock.calls[0][0]).toBeInstanceOf(AbortSignal);          // no gate or camera named
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:frame-1");           // old frames are released
    expect(api.capture).not.toHaveBeenCalled();                                 // live view takes no photo
  });

  it("waits for the frame being fetched before taking the photo, so the camera is free", async () => {
    const frame = deferred<Blob>();
    api.preview.mockReset().mockReturnValue(frame.promise);
    api.capture.mockResolvedValue(picture(1));
    setup();
    await vi.waitFor(() => expect(api.preview).toHaveBeenCalledTimes(1));
    fireEvent.click(takeButton());
    expect(screen.getByText("Taking the photo…")).toBeTruthy();
    await act(async () => {});
    expect(api.capture).not.toHaveBeenCalled();
    await act(async () => frame.resolve(liveFrame));
    await screen.findByTestId("gate-camera-photo");
    expect(api.capture).toHaveBeenCalledTimes(1);
    expect(api.preview).toHaveBeenCalledTimes(1);                              // live view stopped
  });

  it("shows progress and takes one picture at a time", async () => {
    const pending = deferred<Blob>();
    api.capture.mockReturnValue(pending.promise);
    setup();
    await screen.findByTestId("gate-camera-live");
    fireEvent.click(takeButton());
    fireEvent.click(takeButton());                                        // double click
    await vi.waitFor(() => expect(api.capture).toHaveBeenCalledTimes(1));
    expect(api.capture).toHaveBeenCalledWith();                            // no gate or camera named by the browser
    expect(screen.getByText("Taking the photo…")).toBeTruthy();
    expect((takeButton() as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Use webcam" }) as HTMLButtonElement).disabled).toBe(true);
    await act(async () => pending.resolve(picture(1)));
    expect(screen.getByTestId("gate-camera-photo").getAttribute("src")).toBe("blob:gate-1");
    expect(api.capture).toHaveBeenCalledTimes(1);
  });

  it("previews, then Use this photo hands the same picture to the upload", async () => {
    const first = picture(1);
    api.capture.mockResolvedValue(first);
    const { onConfirm } = setup();
    fireEvent.click(takeButton());
    fireEvent.click(await screen.findByRole("button", { name: "Use this photo" }));
    await act(async () => {});
    expect(onConfirm).toHaveBeenCalledWith(first);
  });

  it("Retake drops the previous picture and goes back to the live view", async () => {
    api.capture.mockResolvedValueOnce(picture(1)).mockResolvedValueOnce(picture(2));
    const { onConfirm } = setup();
    fireEvent.click(takeButton());
    fireEvent.click(await screen.findByRole("button", { name: "Retake" }));
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:gate-1");
    await screen.findByTestId("gate-camera-live");
    fireEvent.click(takeButton());
    await screen.findByRole("button", { name: "Use this photo" });
    expect(api.capture).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId("gate-camera-photo").getAttribute("src")).toBe("blob:gate-2");
    expect(onConfirm).not.toHaveBeenCalled();                              // nothing uploaded by taking pictures
  });

  it("keeps the picture and says why when the upload fails", async () => {
    api.capture.mockResolvedValue(picture(1));
    setup(vi.fn().mockRejectedValue(new ApiError(422, "invalid_photo", "The photo could not be read. Please take it again.")));
    fireEvent.click(takeButton());
    fireEvent.click(await screen.findByRole("button", { name: "Use this photo" }));
    expect(await screen.findByText("The photo was not saved: The photo could not be read. Please take it again.")).toBeTruthy();
    expect(screen.getByTestId("gate-camera-photo")).toBeTruthy();
  });

  it("keeps trying while the camera is busy with another request", async () => {
    api.preview.mockReset()
      .mockRejectedValueOnce(new ApiError(409, "gate_camera_busy", "The gate camera is busy. Try again in a moment."))
      .mockResolvedValue(liveFrame);
    setup();
    await screen.findByTestId("gate-camera-live", undefined, { timeout: 3000 });
    expect(screen.queryByRole("alert")).toBeNull();
  });

  const failures = [
    ["timeout", new ApiError(502, "camera_timeout", "The camera did not answer in time.")],
    ["authentication", new ApiError(502, "camera_authentication_failed", "The camera refused the user name or password.")],
    ["invalid response", new ApiError(502, "camera_invalid_response", "The camera sent an unexpected answer.")],
    ["unavailable", new ApiError(502, "camera_unavailable", "The camera cannot be reached. Check that it is switched on and connected.")],
    ["unusable settings", new ApiError(409, "gate_camera_unavailable", "The gate camera cannot be used right now. Use the webcam and tell the administrator.")],
    ["forbidden", new ApiError(403, "forbidden", "You do not have permission to do this.")],
    ["network", new ApiError(0, "network_error", "Cannot reach the server. Check the network connection.")],
  ] as const;

  async function expectExplained(error: ApiError, onUseWebcam: () => void) {
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain(error.message);
    expect(alert.textContent).toContain("You can use the webcam, or continue without a photo.");
    expect(alert.textContent).not.toContain(error.code);
    expect(screen.getByRole("button", { name: "Try the gate camera again" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Use webcam" }));
    expect(onUseWebcam).toHaveBeenCalled();
  }

  it.each(failures)("a %s failure of the photo is explained safely and offers the webcam", async (_, error) => {
    api.capture.mockRejectedValue(error);
    const { onUseWebcam } = setup();
    fireEvent.click(takeButton());
    await expectExplained(error, onUseWebcam);
  });

  it.each(failures)("a %s failure of the live view stops it, is explained and offers the webcam", async (_, error) => {
    api.preview.mockReset().mockRejectedValue(error);
    const { onUseWebcam } = setup();
    await expectExplained(error, onUseWebcam);
    expect(api.preview).toHaveBeenCalledTimes(1);                         // one failed login, not a stream of them
  });

  it("Try again restarts the live view after a problem", async () => {
    api.preview.mockReset().mockRejectedValueOnce(new ApiError(502, "camera_timeout", "The camera did not answer in time."))
      .mockResolvedValue(liveFrame);
    setup();
    fireEvent.click(await screen.findByRole("button", { name: "Try the gate camera again" }));
    expect(await screen.findByTestId("gate-camera-live")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("forgets an unused picture and stops the live view when the step is left, and never stores it in the browser", async () => {
    api.capture.mockResolvedValue(picture(1));
    const { unmount } = render(<GateCameraCapture onConfirm={vi.fn()} onUseWebcam={vi.fn()} />);
    fireEvent.click(takeButton());
    await screen.findByTestId("gate-camera-photo");
    unmount();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:gate-1");
    expect(setItem).not.toHaveBeenCalled();
    expect(localStorage.length + sessionStorage.length).toBe(0);
  });

  it("stops asking for frames when the step is left", async () => {
    const { unmount } = render(<GateCameraCapture onConfirm={vi.fn()} onUseWebcam={vi.fn()} />);
    await screen.findByTestId("gate-camera-live");
    unmount();
    const asked = api.preview.mock.calls.length;
    await new Promise((r) => setTimeout(r, 400));
    expect(api.preview.mock.calls.length).toBe(asked);
  });
});
