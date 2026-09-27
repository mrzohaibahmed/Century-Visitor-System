/**
 * The single way the browser talks to the backend.
 *
 * - Same-origin requests to /api/v1/* (cookies stay first-party; no CORS).
 * - Unsafe methods send the CSRF token from the `cg_csrf` cookie as
 *   X-CSRF-Token (the session cookie itself is HttpOnly; Phase 2).
 * - Every failure becomes an ApiError carrying the backend's error envelope
 *   {error: {code, message, request_id}}; messages are safe to show to users.
 */

export const API_BASE = "/api/v1";
export const CSRF_COOKIE = "cg_csrf";
export const CSRF_HEADER = "X-CSRF-Token";

const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

export type ApiErrorDetail = { field: string; message: string };

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string | null;
  readonly details: ApiErrorDetail[];

  constructor(status: number, code: string, message: string, requestId: string | null = null,
              details: ApiErrorDetail[] = []) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.requestId = requestId;
    this.details = details;
  }

  get isNetworkError(): boolean {
    return this.status === 0;
  }
}

const FALLBACK_MESSAGES: Record<number, string> = {
  401: "Please log in.",
  403: "You do not have permission to do this.",
  404: "Not found.",
  429: "Too many attempts. Please wait a moment and try again.",
};

/** A message that is safe to show for any thrown value. */
export function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : "Something went wrong. Please try again.";
}

/**
 * Validation messages keyed by top-level request field ("body.identity.number" → "identity").
 * Whole-body rules (no field) are keyed "_form".
 */
export function fieldErrors(error: unknown): Record<string, string> {
  if (!(error instanceof ApiError)) return {};
  const out: Record<string, string> = {};
  for (const d of error.details) {
    const key = d.field.replace(/^(body|query|path)\.?/, "").split(".")[0] || "_form";
    out[key] ??= d.message;
  }
  return out;
}

export type RequestOptions = {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
  /** Statuses whose JSON body is returned instead of thrown (e.g. 503 from /health/ready). */
  acceptStatuses?: number[];
  /** Do not treat a 401 as "session ended" (the login request itself). */
  skipSessionExpiry?: boolean;
};

type SessionExpiredHandler = (error: ApiError) => void;
let onSessionExpired: SessionExpiredHandler | null = null;

/** The session layer registers what happens when the server says the session is gone (401). */
export function setSessionExpiredHandler(handler: SessionExpiredHandler | null): void {
  onSessionExpired = handler;
}

export function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  for (const part of document.cookie.split(";")) {
    const [key, ...rest] = part.trim().split("=");
    if (key === name) return decodeURIComponent(rest.join("="));
  }
  return null;
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = options.method ?? "GET";
  const headers: Record<string, string> = { Accept: "application/json" };
  let body: string | undefined;
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.body);
  }
  if (UNSAFE_METHODS.has(method)) {
    const csrf = readCookie(CSRF_COOKIE);
    if (csrf) headers[CSRF_HEADER] = csrf;
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method,
      headers,
      body,
      signal: options.signal,
      credentials: "same-origin",
      cache: "no-store",
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(0, "network_error", "Cannot reach the server. Check the network connection.");
  }

  const isJson = (response.headers.get("content-type") ?? "").includes("application/json");
  const payload: unknown = isJson ? await response.json().catch(() => null) : null;

  if (response.ok || options.acceptStatuses?.includes(response.status)) {
    return payload as T;
  }

  const envelope = (payload as { error?: { code?: string; message?: string; request_id?: string;
    details?: ApiErrorDetail[] } } | null)?.error;
  const error = new ApiError(
    response.status,
    envelope?.code ?? "http_error",
    envelope?.message ?? FALLBACK_MESSAGES[response.status] ?? "Something went wrong. Please try again.",
    envelope?.request_id ?? response.headers.get("x-request-id"),
    envelope?.details ?? [],
  );
  if (response.status === 401 && !options.skipSessionExpiry) onSessionExpired?.(error);
  throw error;
}
