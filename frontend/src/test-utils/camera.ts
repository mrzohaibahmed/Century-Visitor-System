/**
 * A fake webcam for unit tests (jsdom has no camera, video playback or canvas).
 * installCamera() makes getUserMedia resolve with a stream whose tracks record
 * stop(), or reject with the given DOMException name.
 */
import { vi } from "vitest";

export type FakeCamera = {
  getUserMedia: ReturnType<typeof vi.fn>;
  /** Every track handed out so far; `stopped` tells whether the camera was released. */
  tracks: { stop: ReturnType<typeof vi.fn>; stopped: boolean }[];
};

export function installCamera(options: { fail?: string; secure?: boolean; supported?: boolean } = {}): FakeCamera {
  const tracks: FakeCamera["tracks"] = [];
  const getUserMedia = vi.fn(async () => {
    if (options.fail) throw new DOMException("camera problem", options.fail);
    const track = { stopped: false, stop: vi.fn(() => { track.stopped = true; }) };
    tracks.push(track);
    return { getTracks: () => [track] } as unknown as MediaStream;
  });
  Object.defineProperty(window, "isSecureContext", { configurable: true, value: options.secure ?? true });
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: options.supported === false ? undefined : { getUserMedia },
  });
  // A "playing" 640 × 480 video, and a canvas that produces a small JPEG blob.
  vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
  Object.defineProperty(HTMLVideoElement.prototype, "videoWidth", { configurable: true, get: () => 640 });
  Object.defineProperty(HTMLVideoElement.prototype, "videoHeight", { configurable: true, get: () => 480 });
  Object.defineProperty(HTMLVideoElement.prototype, "srcObject", { configurable: true, writable: true, value: null });
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(
    { drawImage: vi.fn() } as unknown as CanvasRenderingContext2D);
  vi.spyOn(HTMLCanvasElement.prototype, "toBlob").mockImplementation(function (callback: BlobCallback) {
    callback(new Blob([new Uint8Array([0xff, 0xd8, 0xff])], { type: "image/jpeg" }));
  });
  if (!URL.createObjectURL) {
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: () => "blob:test" });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: () => {} });
  } else {
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:test");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
  }
  return { getUserMedia, tracks };
}
