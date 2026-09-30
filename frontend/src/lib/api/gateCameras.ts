import { apiBlob, apiRequest } from "./client";

/**
 * Gate cameras (administrators). Mirrors app/schemas/gate_cameras.py.
 * The camera password is only ever SENT (when set or changed); the API never returns it,
 * only whether one is saved. It is never kept anywhere in the browser beyond the open form.
 */
export type PasswordStatus = "NOT_SET" | "SAVED" | "UNREADABLE";
export type CameraProtocol = "http" | "https";

export type CameraLastTest = {
  tested_at: string;
  ok: boolean;
  code: string | null;
  message: string | null;
  model: string | null;
  firmware: string | null;
  device_name: string | null;
};

export type GateCamera = {
  gate_id: string;
  gate_name: string;
  gate_active: boolean;
  configured: boolean;
  enabled: boolean;
  host: string | null;
  protocol: CameraProtocol | null;
  port: number | null;
  channel: number | null;
  username: string | null;
  password_status: PasswordStatus;
  timeout_seconds: number | null;
  updated_at: string | null;
  last_test: CameraLastTest | null;
};

/** `password` omitted: keep the saved one (the API refuses that if the destination changed). */
export type GateCameraInput = {
  enabled: boolean;
  host: string;
  protocol: CameraProtocol;
  port: number | null;
  channel: number;
  username: string;
  password?: string;
  timeout_seconds: number;
};

export type CameraTest = {
  status: "CONNECTED" | "FAILED";
  tested_at: string;
  code: string | null;
  message: string | null;
  model: string | null;
  firmware: string | null;
  device_name: string | null;
};

export type TestPhoto = { blob: Blob; cameraSize: [number, number] | null; photoSize: [number, number] | null };

const path = (gateId: string) => `/gate-cameras/${encodeURIComponent(gateId)}`;

export function listGateCameras(): Promise<GateCamera[]> {
  return apiRequest<GateCamera[]>("/gate-cameras");
}

export function saveGateCamera(gateId: string, input: GateCameraInput): Promise<GateCamera> {
  return apiRequest<GateCamera>(path(gateId), { method: "PUT", body: input });
}

export function removeGateCamera(gateId: string): Promise<void> {
  return apiRequest<void>(path(gateId), { method: "DELETE" });
}

export function testGateCamera(gateId: string): Promise<CameraTest> {
  return apiRequest<CameraTest>(`${path(gateId)}/test`, { method: "POST" });
}

/** One picture from the camera, as the VMS would keep it. Not stored by the server or here. */
export async function captureTestPhoto(gateId: string): Promise<TestPhoto> {
  const { blob, headers } = await apiBlob(`${path(gateId)}/test-photo`, { method: "POST" });
  const size = (w: string, h: string): [number, number] | null => {
    const width = Number(headers.get(w)), height = Number(headers.get(h));
    return width > 0 && height > 0 ? [width, height] : null;
  };
  return { blob, cameraSize: size("x-camera-width", "x-camera-height"), photoSize: size("x-photo-width", "x-photo-height") };
}

// ---------------------------------------------------------------- check-in (guards)
// No gate or camera is ever named here: the server uses the camera of this session's gate.

/** Whether this session's gate has a camera for visitor photos. Does not contact the camera. */
export function sessionGateCamera(): Promise<{ available: boolean }> {
  return apiRequest<{ available: boolean }>("/gate-camera");
}

/** One live-view frame from this session's gate camera, for showing what it sees. Never uploaded. */
export async function gateCameraPreviewFrame(signal?: AbortSignal): Promise<Blob> {
  return (await apiBlob("/gate-camera/preview", { signal })).blob;
}

/** A preview picture from this session's gate camera. Not stored: "Use this photo" uploads it
 *  like a webcam photo (uploadVisitorPhoto → POST /visitors/{id}/photo). */
export async function captureGateCameraPhoto(): Promise<Blob> {
  return (await apiBlob("/gate-camera/snapshot", { method: "POST" })).blob;
}
