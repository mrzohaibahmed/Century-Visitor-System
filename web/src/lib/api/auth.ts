import { apiRequest } from "./client";

/** Mirrors app/schemas/users.py (UserOut, MeResponse). */
export type Role = "ADMIN" | "GUARD";

export type User = {
  id: string;
  username: string;
  display_name: string | null;
  role: Role;
  is_active: boolean;
  must_change_password: boolean;
  locked: boolean;
  last_login_at: string | null;
  created_at: string;
  updated_at: string;
};

export type GateRef = { id: string; name: string };

export type Me = {
  user: User;
  permissions: string[];
  session: {
    expires_at: string;
    idle_timeout_minutes: number;
    /** The gate this session works at (recorded on every check-in / check-out). */
    gate: GateRef | null;
    /** Several gates exist and none has been chosen yet. */
    gate_selection_required: boolean;
  };
};

export function login(username: string, password: string): Promise<Me> {
  return apiRequest<Me>("/auth/login", { method: "POST", body: { username, password }, skipSessionExpiry: true });
}

export function logout(): Promise<void> {
  return apiRequest<void>("/auth/logout", { method: "POST", skipSessionExpiry: true });
}

export function getMe(signal?: AbortSignal): Promise<Me> {
  return apiRequest<Me>("/auth/me", { signal });
}

export function changePassword(currentPassword: string, newPassword: string): Promise<void> {
  return apiRequest<void>("/auth/change-password", {
    method: "POST",
    body: { current_password: currentPassword, new_password: newPassword },
  });
}

export function selectGate(gateId: string): Promise<Me> {
  return apiRequest<Me>("/auth/session/gate", { method: "PUT", body: { gate_id: gateId } });
}

/** Only same-site relative paths may be used after login (no open redirects). */
export function safeNextPath(value: string | null | undefined): string {
  if (!value || !value.startsWith("/") || value.startsWith("//") || value.startsWith("/\\")) return "/dashboard";
  if (value.startsWith("/login")) return "/dashboard";
  return value;
}
