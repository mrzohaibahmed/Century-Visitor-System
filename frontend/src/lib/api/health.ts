import { apiRequest } from "./client";

/** Mirrors ReadyResponse in api/app/api/v1/health.py. */
export type CheckState = "ok" | "unavailable" | "missing" | "outdated" | "unknown";

export type ReadyResponse = {
  status: "ready" | "not_ready";
  checks: {
    database: CheckState;
    schema_version: CheckState;
    transactions: CheckState;
    photo_storage: CheckState;
  };
};

export type LiveResponse = { status: "ok"; version: string };

export function getReadiness(signal?: AbortSignal): Promise<ReadyResponse> {
  // 503 still carries the check details, so it is returned rather than thrown.
  return apiRequest<ReadyResponse>("/health/ready", { signal, acceptStatuses: [503] });
}

export function getLiveness(signal?: AbortSignal): Promise<LiveResponse> {
  return apiRequest<LiveResponse>("/health/live", { signal });
}
