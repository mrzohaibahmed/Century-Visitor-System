import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiRequest, setSessionExpiredHandler } from "./client";

function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...headers },
  });
}

function mockFetch(response: Response | Error) {
  const fn = vi.fn(() => (response instanceof Error ? Promise.reject(response) : Promise.resolve(response)));
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => {
  vi.unstubAllGlobals();
  setSessionExpiredHandler(null);
  document.cookie = "cg_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
});

describe("apiRequest", () => {
  it("calls the same-origin API with credentials and returns JSON", async () => {
    const fetchMock = mockFetch(jsonResponse(200, { status: "ok" }));
    await expect(apiRequest("/health/live")).resolves.toEqual({ status: "ok" });
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/v1/health/live");
    expect(init.credentials).toBe("same-origin");
    expect(init.cache).toBe("no-store");
  });

  it("turns the backend error envelope into an ApiError with a safe message", async () => {
    mockFetch(jsonResponse(403, { error: { code: "forbidden", message: "Not allowed.", request_id: "req-1" } }));
    const error = await apiRequest("/users").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 403, code: "forbidden", message: "Not allowed.", requestId: "req-1" });
  });

  it("includes field details from validation errors", async () => {
    mockFetch(jsonResponse(422, { error: { code: "validation_error", message: "The request is not valid.",
      request_id: "req-2", details: [{ field: "body.name", message: "Field required" }] } }));
    const error = (await apiRequest("/visitors", { method: "POST", body: {} }).catch((e: unknown) => e)) as ApiError;
    expect(error.details).toEqual([{ field: "body.name", message: "Field required" }]);
  });

  it("uses a friendly fallback when the response is not the envelope", async () => {
    mockFetch(new Response("<html>Bad gateway</html>", { status: 502, headers: { "x-request-id": "req-3" } }));
    const error = (await apiRequest("/visits").catch((e: unknown) => e)) as ApiError;
    expect(error.status).toBe(502);
    expect(error.message).toBe("Something went wrong. Please try again.");
    expect(error.requestId).toBe("req-3");
    expect(error.message).not.toContain("html");
  });

  it("reports network failures clearly", async () => {
    mockFetch(new TypeError("Failed to fetch"));
    const error = (await apiRequest("/health/live").catch((e: unknown) => e)) as ApiError;
    expect(error.isNetworkError).toBe(true);
    expect(error.message).toMatch(/cannot reach the server/i);
  });

  it("returns the body for explicitly accepted error statuses", async () => {
    mockFetch(jsonResponse(503, { status: "not_ready" }));
    await expect(apiRequest("/health/ready", { acceptStatuses: [503] })).resolves.toEqual({ status: "not_ready" });
  });

  it("sends the CSRF token on unsafe methods only", async () => {
    document.cookie = "cg_csrf=token-123";
    const fetchMock = mockFetch(jsonResponse(200, {}));
    await apiRequest("/visits", { method: "POST", body: { a: 1 } });
    mockFetch(jsonResponse(200, {}));
    const getMock = vi.mocked(fetch);
    await apiRequest("/visits");
    const post = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    const get = getMock.mock.calls[0] as unknown as [string, RequestInit];
    expect((post[1].headers as Record<string, string>)["X-CSRF-Token"]).toBe("token-123");
    expect((post[1].headers as Record<string, string>)["Content-Type"]).toBe("application/json");
    expect(post[1].body).toBe('{"a":1}');
    expect((get[1].headers as Record<string, string>)["X-CSRF-Token"]).toBeUndefined();
  });

  it("reports an ended session (401) to the registered handler", async () => {
    const handler = vi.fn();
    setSessionExpiredHandler(handler);
    mockFetch(jsonResponse(401, { error: { code: "session_expired", message: "Your session has expired.", request_id: "r" } }));
    await expect(apiRequest("/users")).rejects.toMatchObject({ status: 401, code: "session_expired" });
    expect(handler).toHaveBeenCalledOnce();
  });

  it("does not treat a failed login as an ended session", async () => {
    const handler = vi.fn();
    setSessionExpiredHandler(handler);
    mockFetch(jsonResponse(401, { error: { code: "invalid_credentials", message: "Invalid username or password.", request_id: "r" } }));
    await expect(apiRequest("/auth/login", { method: "POST", body: {}, skipSessionExpiry: true })).rejects.toBeInstanceOf(ApiError);
    expect(handler).not.toHaveBeenCalled();
  });

  it("does not report other errors as an ended session", async () => {
    const handler = vi.fn();
    setSessionExpiredHandler(handler);
    mockFetch(jsonResponse(403, { error: { code: "forbidden", message: "No.", request_id: "r" } }));
    await expect(apiRequest("/users")).rejects.toBeInstanceOf(ApiError);
    expect(handler).not.toHaveBeenCalled();
  });
});
