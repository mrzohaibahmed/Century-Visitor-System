import { apiRequest } from "./client";

/** Mirrors app/schemas/directory.py. */
export type Gate = { id: string; name: string; location: string | null; is_active: boolean };
export type Department = { id: string; name: string; notification_email: string | null; is_active: boolean };
export type Host = {
  id: string;
  name: string;
  email: string | null;
  phone: string | null;
  department_id: string | null;
  department_name: string | null;
  is_active: boolean;
};

export type DirectoryKind = "gates" | "departments" | "hosts";

function query(params: Record<string, string | boolean | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "" && value !== false) search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

/** Inactive entries are only returned to administrators (the API ignores the flag for guards). */
export function listGates(includeInactive = false, signal?: AbortSignal): Promise<Gate[]> {
  return apiRequest<Gate[]>(`/gates${query({ include_inactive: includeInactive })}`, { signal });
}

export function listDepartments(includeInactive = false, signal?: AbortSignal): Promise<Department[]> {
  return apiRequest<Department[]>(`/departments${query({ include_inactive: includeInactive })}`, { signal });
}

export function listHosts(options: { q?: string; departmentId?: string; includeInactive?: boolean } = {},
                          signal?: AbortSignal): Promise<Host[]> {
  return apiRequest<Host[]>(`/hosts${query({
    q: options.q?.trim(), department_id: options.departmentId, include_inactive: options.includeInactive,
  })}`, { signal });
}

export function createEntry<T>(kind: DirectoryKind, body: Record<string, unknown>): Promise<T> {
  return apiRequest<T>(`/${kind}`, { method: "POST", body });
}

export function updateEntry<T>(kind: DirectoryKind, id: string, body: Record<string, unknown>): Promise<T> {
  return apiRequest<T>(`/${kind}/${encodeURIComponent(id)}`, { method: "PATCH", body });
}
