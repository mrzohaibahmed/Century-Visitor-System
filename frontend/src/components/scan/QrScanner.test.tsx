import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CAMERA_MESSAGES } from "@/components/camera/camera";
import { ApiError } from "@/lib/api/client";
import { looksLikePass } from "@/lib/api/passes";
import { installCamera } from "@/test-utils/camera";

import { QrScanner } from "./QrScanner";

const api = { session: vi.fn(), preview: vi.fn() };
vi.mock("@/lib/api/gateCameras", async (original) => ({
  ...(await original<typeof import("@/lib/api/gateCameras")>()),
  sessionGateCamera: (...a: unknown[]) => api.session(...a),
  gateCameraPreviewFrame: (...a: unknown[]) => api.preview(...a),
}));
const decoded = vi.fn();
vi.mock("jsqr", () => ({ default: (...a: unknown[]) => decoded(...a) }));

const PASS = `CGP1:${"A".repeat(64)}`;
const frame = new Blob([new Uint8Array([0xff, 0xd8, 0xff])], { type: "image/jpeg" });

beforeEach(() => {
  api.session.mockReset().mockResolvedValue({ available: false });
  api.preview.mockReset().mockResolvedValue(frame);
  decoded.mockReset().mockReturnValue(null);
  URL.createObjectURL = vi.fn(() => "blob:frame");
  URL.revokeObjectURL = vi.fn();
  // jsdom has no createImageBitmap or canvas: a frame "decodes" to a 1280 × 720 bitmap.
  globalThis.createImageBitmap = vi.fn(async () => ({ width: 1280, height: 720, close: vi.fn() })) as never;
  HTMLCanvasElement.prototype.getContext = vi.fn(() => ({
    drawImage: vi.fn(), getImageData: (_x: number, _y: number, w: number, h: number) => ({ data: new Uint8ClampedArray(4), width: w, height: h }),
  })) as never;
});
afterEach(cleanup);

describe("QrScanner with the gate camera", () => {
  beforeEach(() => { api.session.mockResolvedValue({ available: true }); });

  it("scans the badge from the gate camera's live view and stops asking for frames", async () => {
    const camera = installCamera();
    decoded.mockReturnValueOnce(null).mockReturnValue({ data: PASS });
    const onScan = vi.fn();
    render(<QrScanner onScan={onScan} onCancel={vi.fn()} />);
    expect(await screen.findByText(/in front of the gate camera/)).toBeTruthy();
    await vi.waitFor(() => expect(onScan).toHaveBeenCalledWith(PASS));
    expect(onScan).toHaveBeenCalledTimes(1);
    const asked = api.preview.mock.calls.length;
    await new Promise((r) => setTimeout(r, 400));
    expect(api.preview.mock.calls.length).toBe(asked);
    expect(camera.getUserMedia).not.toHaveBeenCalled();                     // the webcam is not opened
  });

  it("says when a code is not a visitor pass and keeps scanning", async () => {
    decoded.mockReturnValue({ data: "https://example.com" });
    const onScan = vi.fn();
    render(<QrScanner onScan={onScan} onCancel={vi.fn()} />);
    expect(await screen.findByText("That code is not a Century Gate visitor pass.")).toBeTruthy();
    await vi.waitFor(() => expect(api.preview.mock.calls.length).toBeGreaterThan(2));
    expect(onScan).not.toHaveBeenCalled();
  });

  it("explains a gate camera problem, can try again, and offers the webcam", async () => {
    api.preview.mockRejectedValueOnce(new ApiError(502, "camera_timeout", "The camera did not answer in time."));
    render(<QrScanner onScan={vi.fn()} onCancel={vi.fn()} />);
    expect((await screen.findByRole("alert")).textContent).toContain("The camera did not answer in time.");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByTestId("gate-scanner-live")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("switches to the webcam and back", async () => {
    const camera = installCamera();
    render(<QrScanner onScan={vi.fn()} onCancel={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "Use webcam" }));
    await vi.waitFor(() => expect(camera.tracks).toHaveLength(1));
    fireEvent.click(screen.getByRole("button", { name: "Use the gate camera instead" }));
    await vi.waitFor(() => expect(camera.tracks[0].stopped).toBe(true));      // webcam released
    expect(await screen.findByText(/in front of the gate camera/)).toBeTruthy();
  });
});

describe("QrScanner", () => {
  it("starts the camera and releases it when closed", async () => {
    const camera = installCamera();
    const { unmount } = render(<QrScanner onScan={vi.fn()} onCancel={vi.fn()} />);
    await vi.waitFor(() => expect(camera.tracks).toHaveLength(1));
    unmount();
    await vi.waitFor(() => expect(camera.tracks[0].stopped).toBe(true));
  });

  it("explains a refused camera and can try again", async () => {
    const camera = installCamera({ fail: "NotAllowedError" });
    render(<QrScanner onScan={vi.fn()} onCancel={vi.fn()} />);
    expect(await screen.findByText(CAMERA_MESSAGES.denied)).toBeTruthy();
    camera.getUserMedia.mockResolvedValueOnce({ getTracks: () => [] } as unknown as MediaStream);
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await vi.waitFor(() => expect(camera.getUserMedia).toHaveBeenCalledTimes(2));
  });

  it("can be cancelled", () => {
    installCamera();
    const onCancel = vi.fn();
    render(<QrScanner onScan={vi.fn()} onCancel={onCancel} />);
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalled();
  });

  it("uses the webcam when this gate has no camera, without offering the gate camera", async () => {
    const camera = installCamera();
    render(<QrScanner onScan={vi.fn()} onCancel={vi.fn()} />);
    await vi.waitFor(() => expect(camera.tracks).toHaveLength(1));
    expect(api.session).toHaveBeenCalledWith();                              // the server picks the camera
    expect(api.preview).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: /gate camera/ })).toBeNull();
  });
});

describe("looksLikePass", () => {
  it.each([[`CGP1:${"A".repeat(64)}`, true], [` cgp1:${"a".repeat(64)} `, true], ["V-2026-000001", false],
           ["35201-1234567-1", false]])("%s → %s", (text, expected) => {
    expect(looksLikePass(text)).toBe(expected);
  });
});
