import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { User } from "@/lib/api/auth";

const updateUser = vi.fn();
vi.mock("@/lib/api/users", () => ({
  updateUser: (...args: unknown[]) => updateUser(...args),
  createUser: vi.fn(), listUsers: vi.fn(), resetPassword: vi.fn(), unlockUser: vi.fn(),
}));
vi.mock("@/components/session/SessionProvider", () => ({ useSession: vi.fn() }));

const { EditUserForm } = await import("./UsersManager");

const GUARD: User = {
  id: "u1", username: "guard1", display_name: "Gate One", role: "GUARD", is_active: true,
  must_change_password: false, locked: false, last_login_at: null, created_at: "", updated_at: "",
};

beforeEach(() => updateUser.mockReset());
afterEach(cleanup);

describe("EditUserForm", () => {
  it("changes the name without asking for a password", async () => {
    updateUser.mockResolvedValue(GUARD);
    render(<EditUserForm user={GUARD} isSelf={false} onDone={vi.fn()} onCancel={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Full name"), { target: { value: "Main Gate" } });
    expect(screen.queryByLabelText("Your password (to confirm)")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(updateUser).toHaveBeenCalledWith("u1", { display_name: "Main Gate" }));
  });

  it("requires the admin's password to change the role", async () => {
    updateUser.mockResolvedValue(GUARD);
    render(<EditUserForm user={GUARD} isSelf={false} onDone={vi.fn()} onCancel={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Role"), { target: { value: "ADMIN" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(screen.getByRole("alert").textContent).toMatch(/your own password/);
    expect(updateUser).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Your password (to confirm)"), { target: { value: "Admin-Pass-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(updateUser).toHaveBeenCalledWith("u1", { role: "ADMIN", confirm_password: "Admin-Pass-1" }));
  });

  it("warns before disabling an account", () => {
    render(<EditUserForm user={GUARD} isSelf={false} onDone={vi.fn()} onCancel={vi.fn()} />);
    fireEvent.click(screen.getByLabelText("Account active (can log in)"));
    expect(screen.getByText(/signs guard1 out everywhere/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Disable account" })).toBeTruthy();
  });

  it("does not let admins change their own role or disable themselves", () => {
    render(<EditUserForm user={{ ...GUARD, role: "ADMIN" }} isSelf onDone={vi.fn()} onCancel={vi.fn()} />);
    expect((screen.getByLabelText("Role") as HTMLSelectElement).disabled).toBe(true);
    expect((screen.getByLabelText("Account active (can log in)") as HTMLInputElement).disabled).toBe(true);
  });
});
