import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { User } from "@/lib/api/auth";
import type { Host } from "@/lib/api/directory";

const api = { createEntry: vi.fn(), updateEntry: vi.fn() };
vi.mock("@/lib/api/directory", async (original) => ({
  ...(await original<typeof import("@/lib/api/directory")>()),
  createEntry: (...a: unknown[]) => api.createEntry(...a),
  updateEntry: (...a: unknown[]) => api.updateEntry(...a),
}));

const { EntryForm } = await import("./DirectoryManager");

const user = (id: string, username: string, name: string): User => ({
  id, username, display_name: name, role: "GUARD", is_active: true, must_change_password: false, locked: false,
  last_login_at: null, created_at: "", updated_at: "",
});
const USERS = [user("u1", "reception", "Reception Desk"), user("u2", "security", "Security Office")];
const HOST: Host = {
  id: "h1", name: "Sara Ahmed", email: "sara@century.test", phone: null, department_id: "d1", department_name: "HR",
  is_active: true, linked_user: { id: "u1", name: "Reception Desk" },
};

beforeEach(() => Object.values(api).forEach((fn) => fn.mockReset()));
afterEach(cleanup);

function renderForm(entry: Host | null) {
  const onDone = vi.fn();
  render(<EntryForm kind="hosts" entry={entry} departments={[]} users={USERS} onDone={onDone} onCancel={vi.fn()} />);
  return onDone;
}

describe("host form: Linked app account", () => {
  it("links an app account when adding a host", async () => {
    api.createEntry.mockResolvedValue({ ...HOST, id: "h2" });
    renderForm(null);
    fireEvent.change(screen.getByLabelText("Full name"), { target: { value: "Imran Ali" } });
    fireEvent.change(screen.getByLabelText("Linked app account"), { target: { value: "u2" } });
    fireEvent.submit(screen.getByLabelText("Full name").closest("form")!);
    await waitFor(() => expect(api.createEntry).toHaveBeenCalledWith("hosts", { name: "Imran Ali", linked_user_id: "u2" }));
  });

  it("changes and removes the link, and sends nothing when it is unchanged", async () => {
    api.updateEntry.mockResolvedValue(HOST);
    renderForm(HOST);
    expect((screen.getByLabelText("Linked app account") as HTMLSelectElement).value).toBe("u1");
    fireEvent.change(screen.getByLabelText("Linked app account"), { target: { value: "" } });
    fireEvent.submit(screen.getByLabelText("Full name").closest("form")!);
    await waitFor(() => expect(api.updateEntry).toHaveBeenCalledWith("hosts", "h1", { clear_linked_user: true }));
    cleanup();

    renderForm(HOST);
    fireEvent.change(screen.getByLabelText("Linked app account"), { target: { value: "u2" } });
    fireEvent.submit(screen.getByLabelText("Full name").closest("form")!);
    await waitFor(() => expect(api.updateEntry).toHaveBeenLastCalledWith("hosts", "h1", { linked_user_id: "u2" }));
  });

  it("is only offered for hosts", () => {
    render(<EntryForm kind="gates" entry={null} departments={[]} onDone={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.queryByLabelText("Linked app account")).toBeNull();
  });
});

describe("host form: phone validation", () => {
  it("rejects an invalid phone before submitting", async () => {
    renderForm(null);
    fireEvent.change(screen.getByLabelText("Full name"), { target: { value: "Imran Ali" } });
    fireEvent.change(screen.getByLabelText("Phone"), { target: { value: "13001234567" } });
    fireEvent.submit(screen.getByLabelText("Full name").closest("form")!);

    expect(await screen.findByText(/valid Pakistani phone number/i)).toBeTruthy();
    expect(api.createEntry).not.toHaveBeenCalled();
  });

  it("normalises a valid international phone before submitting", async () => {
    api.createEntry.mockResolvedValue({ ...HOST, id: "h2", phone: "+923001234567" });
    renderForm(null);
    fireEvent.change(screen.getByLabelText("Full name"), { target: { value: "Imran Ali" } });
    fireEvent.change(screen.getByLabelText("Phone"), { target: { value: "+92 300 1234567" } });
    fireEvent.submit(screen.getByLabelText("Full name").closest("form")!);

    await waitFor(() => expect(api.createEntry).toHaveBeenCalledWith("hosts", {
      name: "Imran Ali",
      phone: "+923001234567",
    }));
  });
});
