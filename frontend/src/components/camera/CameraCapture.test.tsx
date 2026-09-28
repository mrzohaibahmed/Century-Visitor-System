import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/client";
import { installCamera } from "@/test-utils/camera";

import { CAMERA_MESSAGES, cameraProblem } from "./camera";
import { CameraCapture } from "./CameraCapture";

afterEach(cleanup);

async function startCamera() {
  fireEvent.click(screen.getByRole("button", { name: "Start camera" }));
  return screen.findByRole("button", { name: "Take photo" });
}

describe("cameraProblem", () => {
  it.each([
    ["NotAllowedError", "denied"], ["NotFoundError", "no_camera"], ["OverconstrainedError", "no_camera"],
    ["NotReadableError", "in_use"], ["TypeError", "failed"],
  ])("maps %s to %s", (name, problem) => {
    expect(cameraProblem(new DOMException("x", name))).toBe(problem);
  });
});

describe("CameraCapture", () => {
  it("captures, previews, retakes and confirms, releasing the camera each time", async () => {
    const camera = installCamera();
    const onConfirm = vi.fn().mockResolvedValue(undefined);
    render(<CameraCapture onConfirm={onConfirm} />);
    fireEvent.click(await startCamera());
    expect(await screen.findByTestId("captured-photo")).toBeTruthy();
    expect(camera.tracks[0].stopped).toBe(true);                     // released once the picture is taken

    fireEvent.click(screen.getByRole("button", { name: "Retake" }));
    fireEvent.click(await screen.findByRole("button", { name: "Take photo" }));
    expect(camera.getUserMedia).toHaveBeenCalledTimes(2);
    expect(camera.tracks[1].stopped).toBe(true);

    fireEvent.click(await screen.findByRole("button", { name: "Use this photo" }));
    await waitFor(() => expect(onConfirm).toHaveBeenCalledTimes(1));
    expect((onConfirm.mock.calls[0][0] as Blob).type).toBe("image/jpeg");
  });

  it.each([
    ["NotAllowedError", CAMERA_MESSAGES.denied],
    ["NotFoundError", CAMERA_MESSAGES.no_camera],
    ["NotReadableError", CAMERA_MESSAGES.in_use],
  ])("explains a %s and offers to try again", async (fail, message) => {
    installCamera({ fail });
    render(<CameraCapture onConfirm={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Start camera" }));
    expect(await screen.findByText(message)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Try the camera again" })).toBeTruthy();
  });

  it("explains when the page is not on HTTPS or the browser has no camera support", async () => {
    installCamera({ secure: false });
    const { unmount } = render(<CameraCapture onConfirm={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Start camera" }));
    expect(await screen.findByText(CAMERA_MESSAGES.insecure)).toBeTruthy();
    unmount();
    installCamera({ supported: false });
    render(<CameraCapture onConfirm={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Start camera" }));
    expect(await screen.findByText(CAMERA_MESSAGES.unsupported)).toBeTruthy();
  });

  it("keeps the photo and shows the error when the upload fails", async () => {
    installCamera();
    const onConfirm = vi.fn().mockRejectedValueOnce(new ApiError(422, "invalid_photo", "The photo could not be read."))
      .mockResolvedValueOnce(undefined);
    render(<CameraCapture onConfirm={onConfirm} />);
    fireEvent.click(await startCamera());
    fireEvent.click(await screen.findByRole("button", { name: "Use this photo" }));
    expect(await screen.findByText(/The photo was not saved: The photo could not be read\./)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Use this photo" }));           // retry the same photo
    await waitFor(() => expect(onConfirm).toHaveBeenCalledTimes(2));
  });

  it("keeps Take photo disabled until the video has a frame", async () => {
    installCamera();
    let width = 0;                                                     // camera started, no frame yet
    Object.defineProperty(HTMLVideoElement.prototype, "videoWidth", { configurable: true, get: () => width });
    render(<CameraCapture onConfirm={vi.fn()} />);
    const takePhoto = await startCamera();
    expect((takePhoto as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("Starting camera…")).toBeTruthy();
    width = 640;
    fireEvent(screen.getByLabelText("Camera preview"), new Event("loadeddata"));
    await waitFor(() => expect((takePhoto as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(takePhoto);
    expect(await screen.findByTestId("captured-photo")).toBeTruthy();
  });

  it("says so, instead of doing nothing, when the frame is lost at the moment of capture", async () => {
    installCamera();
    let width = 640;
    Object.defineProperty(HTMLVideoElement.prototype, "videoWidth", { configurable: true, get: () => width });
    render(<CameraCapture onConfirm={vi.fn()} />);
    const takePhoto = await startCamera();
    await waitFor(() => expect((takePhoto as HTMLButtonElement).disabled).toBe(false));
    width = 0;
    fireEvent.click(takePhoto);
    expect(await screen.findByText("Camera not ready, try again.")).toBeTruthy();
    expect((takePhoto as HTMLButtonElement).disabled).toBe(true);
    expect(screen.queryByTestId("captured-photo")).toBeNull();
    width = 640;
    fireEvent(screen.getByLabelText("Camera preview"), new Event("loadeddata"));
    await waitFor(() => expect(screen.queryByText("Camera not ready, try again.")).toBeNull());
    fireEvent.click(takePhoto);
    expect(await screen.findByTestId("captured-photo")).toBeTruthy();
  });

  it("stops the camera when the component goes away", async () => {
    const camera = installCamera();
    const { unmount } = render(<CameraCapture onConfirm={vi.fn()} />);
    await startCamera();
    expect(camera.tracks[0].stopped).toBe(false);
    unmount();
    expect(camera.tracks[0].stopped).toBe(true);
  });

  it("releases a camera that arrives after the component is gone", async () => {
    const camera = installCamera();
    let resolve: (s: MediaStream) => void = () => {};
    const track = { stopped: false, stop: vi.fn() };
    camera.getUserMedia.mockImplementationOnce(() => new Promise((r) => { resolve = r; }));
    const { unmount } = render(<CameraCapture onConfirm={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Start camera" }));
    unmount();
    await act(async () => resolve({ getTracks: () => [track] } as unknown as MediaStream));
    expect(track.stop).toHaveBeenCalled();
  });
});
