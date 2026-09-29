/**
 * Webcam access shared by photo capture and QR scanning.
 *
 * Browsers only allow the camera on a secure origin: https://, or http://localhost
 * on the same PC. Gate PCs reaching the server over plain http:// get no camera
 * at all, so production needs HTTPS (Phase 7).
 */

export type CameraProblem = "insecure" | "unsupported" | "denied" | "no_camera" | "in_use" | "disconnected" | "failed";

export const CAMERA_MESSAGES: Record<CameraProblem, string> = {
  insecure: "The camera only works when this system is opened over HTTPS. Ask the administrator.",
  unsupported: "This browser cannot use a camera. Use a current version of Microsoft Edge or Google Chrome.",
  denied: "Camera access was refused. Click the camera icon in the address bar, allow the camera, then try again.",
  no_camera: "No camera was found. Check that the webcam is plugged in.",
  in_use: "The camera is being used by another program. Close that program, then try again.",
  disconnected: "The camera stopped working. Check that the webcam is plugged in, then try again.",
  failed: "The camera could not be started. Try again, or continue without it.",
};

export function cameraProblem(error: unknown): CameraProblem {
  const name = error instanceof DOMException || error instanceof Error ? error.name : "";
  if (name === "NotAllowedError" || name === "SecurityError" || name === "PermissionDeniedError") return "denied";
  if (name === "NotFoundError" || name === "OverconstrainedError" || name === "DevicesNotFoundError") return "no_camera";
  if (name === "NotReadableError" || name === "TrackStartError" || name === "AbortError") return "in_use";
  return "failed";
}

/** Opens the camera. Throws a CameraProblem string when it cannot. */
export async function openCamera(facingMode: "user" | "environment" = "user"): Promise<MediaStream> {
  if (typeof window !== "undefined" && window.isSecureContext === false) throw "insecure" satisfies CameraProblem;
  if (!navigator.mediaDevices?.getUserMedia) throw "unsupported" satisfies CameraProblem;
  try {
    return await navigator.mediaDevices.getUserMedia({
      video: { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode },
      audio: false,
    });
  } catch (error) {
    throw cameraProblem(error);
  }
}

/** Releases the camera (the webcam light goes off). Safe to call with null or twice. */
export function stopCamera(stream: MediaStream | null): void {
  stream?.getTracks().forEach((track) => track.stop());
}

export function asProblem(error: unknown): CameraProblem {
  return typeof error === "string" && error in CAMERA_MESSAGES ? (error as CameraProblem) : "failed";
}
