import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/client";

import { LoginForm } from "./LoginForm";

const login = vi.fn();
vi.mock("@/lib/api/auth", () => ({ login: (...args: unknown[]) => login(...args) }));

const assign = vi.fn();
beforeEach(() => {
  login.mockReset();
  assign.mockReset();
  vi.stubGlobal("location", { ...window.location, assign });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function fill(username: string, password: string) {
  fireEvent.change(screen.getByLabelText("Username"), { target: { value: username } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: password } });
  fireEvent.click(screen.getByRole("button", { name: "Log in" }));
}

describe("LoginForm", () => {
  it("logs in and goes to the requested page", async () => {
    login.mockResolvedValue({ user: { must_change_password: false } });
    render(<LoginForm next="/users" />);
    fill("  guard1 ", "Guard-Pass-1");
    await waitFor(() => expect(assign).toHaveBeenCalledWith("/users"));
    expect(login).toHaveBeenCalledWith("guard1", "Guard-Pass-1");
  });

  it("sends accounts with a temporary password to change it first", async () => {
    login.mockResolvedValue({ user: { must_change_password: true } });
    render(<LoginForm next="/dashboard" />);
    fill("guard1", "Temp-Pass-123");
    await waitFor(() => expect(assign).toHaveBeenCalledWith("/account/password"));
  });

  it("shows the server's message and clears the password on failure", async () => {
    login.mockRejectedValue(new ApiError(401, "invalid_credentials", "Invalid username or password."));
    render(<LoginForm next="/dashboard" />);
    fill("guard1", "wrong");
    expect(await screen.findByRole("alert")).toHaveProperty("textContent", "Invalid username or password.");
    expect((screen.getByLabelText("Password") as HTMLInputElement).value).toBe("");
    expect(assign).not.toHaveBeenCalled();
  });

  it("asks for both fields before calling the server", () => {
    render(<LoginForm next="/dashboard" />);
    fireEvent.click(screen.getByRole("button", { name: "Log in" }));
    expect(screen.getByRole("alert").textContent).toMatch(/username and password/);
    expect(login).not.toHaveBeenCalled();
  });

  it("explains why the user was sent to the login page", () => {
    render(<LoginForm next="/dashboard" notice="Your session has expired. Please log in again." />);
    expect(screen.getByText("Your session has expired. Please log in again.")).toBeTruthy();
  });
});
