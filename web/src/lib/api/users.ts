import type { Role, User } from "./auth";
import { apiRequest } from "./client";

export function listUsers(signal?: AbortSignal): Promise<{ items: User[] }> {
  return apiRequest<{ items: User[] }>("/users", { signal });
}

export type NewUser = { username: string; display_name: string; role: Role; password: string };

export function createUser(user: NewUser): Promise<User> {
  return apiRequest<User>("/users", { method: "POST", body: user });
}

export type UserChanges = {
  display_name?: string;
  role?: Role;
  is_active?: boolean;
  /** The acting admin's own password: required to change role or active state. */
  confirm_password?: string;
};

export function updateUser(id: string, changes: UserChanges): Promise<User> {
  return apiRequest<User>(`/users/${encodeURIComponent(id)}`, { method: "PATCH", body: changes });
}

export function resetPassword(id: string, newPassword: string, confirmPassword: string): Promise<void> {
  return apiRequest<void>(`/users/${encodeURIComponent(id)}/reset-password`, {
    method: "POST",
    body: { new_password: newPassword, confirm_password: confirmPassword },
  });
}

export function unlockUser(id: string): Promise<User> {
  return apiRequest<User>(`/users/${encodeURIComponent(id)}/unlock`, { method: "POST" });
}
