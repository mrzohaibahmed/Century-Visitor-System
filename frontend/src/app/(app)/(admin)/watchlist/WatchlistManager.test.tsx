import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/client";
import { endOfDayIso, type WatchlistEntry } from "@/lib/api/watchlist";

const api = { list: vi.fn(), add: vi.fn(), update: vi.fn(), expire: vi.fn(), disable: vi.fn() };
vi.mock("@/lib/api/watchlist", async (original) => ({
  ...(await original<typeof import("@/lib/api/watchlist")>()),
  listWatchlist: (...a: unknown[]) => api.list(...a),
  addWatchlistEntry: (...a: unknown[]) => api.add(...a),
  updateWatchlistEntry: (...a: unknown[]) => api.update(...a),
  expireWatchlistEntry: (...a: unknown[]) => api.expire(...a),
  disableWatchlistEntry: (...a: unknown[]) => api.disable(...a),
}));

const { WatchlistManager } = await import("./WatchlistManager");

const ENTRY: WatchlistEntry = {
  id: "w1", identity: { type: "CNIC", number: "35201-1234567-1" }, name: "Ali Khan", reason: "Theft of property.",
  status: "ACTIVE", expires_at: null, created_at: "2026-09-01T08:00:00Z", created_by: { id: "u1", name: "Admin" },
  updated_at: null, disabled_at: null, disabled_by: null, disabled_reason: null,
};

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  api.list.mockResolvedValue({ items: [ENTRY], next_cursor: null });
});
afterEach(cleanup);

// jsdom has no <dialog>.showModal(), so the modal's content counts as hidden.
const inDialog = { hidden: true };

describe("WatchlistManager", () => {
  it("lists active entries with reason, creator, dates and actions", async () => {
    render(<WatchlistManager />);
    const row = await screen.findByTestId("watchlist-row");
    expect(row.textContent).toMatch(/Ali Khan.*35201-1234567-1.*Theft of property\..*Active.*by Admin.*No end date/);
    expect(api.list).toHaveBeenCalledWith({ q: "", status: "ACTIVE" }, null);
    expect(within(row).getByRole("button", { name: "Edit Ali Khan" })).toBeTruthy();
  });

  it("searches with the chosen status", async () => {
    render(<WatchlistManager />);
    await screen.findByTestId("watchlist-row");
    fireEvent.change(screen.getByLabelText("Search watchlist"), { target: { value: "3520112345671" } });
    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    await waitFor(() => expect(api.list).toHaveBeenLastCalledWith({ q: "3520112345671", status: "" }, null));
  });

  it("adds an entry and warns when the person is inside", async () => {
    api.add.mockResolvedValue({ ...ENTRY, inside_visit_number: "V-2026-000007" });
    render(<WatchlistManager />);
    fireEvent.click(screen.getByRole("button", { name: "Add to watchlist" }));
    fireEvent.change(screen.getByLabelText("ID number"), { target: { value: "3520112345671" } });
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "Theft of property." } });
    fireEvent.change(screen.getByLabelText("Ends on (optional)"), { target: { value: "2099-06-30" } });
    fireEvent.submit(screen.getByLabelText("ID number").closest("form")!);
    await waitFor(() => expect(api.add).toHaveBeenCalledWith({
      identity: { type: "CNIC", number: "3520112345671" }, name: null, reason: "Theft of property.",
      expires_at: endOfDayIso("2099-06-30"),
    }));
    expect(await screen.findByText(/INSIDE now \(visit V-2026-000007\)/)).toBeTruthy();
  });

  it("shows the server's message for an invalid ID number", async () => {
    api.add.mockRejectedValue(new ApiError(422, "validation_error", "The request is not valid.", null,
      [{ field: "body.identity.number", message: "A CNIC must have exactly 13 digits." }]));
    render(<WatchlistManager />);
    fireEvent.click(screen.getByRole("button", { name: "Add to watchlist" }));
    fireEvent.change(screen.getByLabelText("ID number"), { target: { value: "123" } });
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "Theft." } });
    fireEvent.submit(screen.getByLabelText("ID number").closest("form")!);
    expect(await screen.findByText("A CNIC must have exactly 13 digits.")).toBeTruthy();
  });

  it("edits only what changed and can remove the end date", async () => {
    api.list.mockResolvedValue({ items: [{ ...ENTRY, expires_at: "2099-01-01T18:00:00Z" }], next_cursor: null });
    api.update.mockResolvedValue(ENTRY);
    render(<WatchlistManager />);
    fireEvent.click(await screen.findByRole("button", { name: "Edit Ali Khan" }));
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "Threatened staff." } });
    fireEvent.change(screen.getByLabelText("Ends on"), { target: { value: "" } });
    fireEvent.submit(screen.getByLabelText("Reason").closest("form")!);
    await waitFor(() => expect(api.update).toHaveBeenCalledWith("w1", { reason: "Threatened staff.", clear_expiry: true }));
    expect(await screen.findByText("Watchlist entry updated.")).toBeTruthy();
  });

  it("disabling needs a reason", async () => {
    api.disable.mockResolvedValue({ ...ENTRY, status: "DISABLED" });
    render(<WatchlistManager />);
    fireEvent.click(await screen.findByRole("button", { name: "Disable Ali Khan" }));
    fireEvent.click(screen.getByRole("button", { name: "Disable entry", ...inDialog }));
    expect(screen.getByText(/Say why the ban is lifted/)).toBeTruthy();
    expect(api.disable).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Why is the ban lifted?"), { target: { value: "Cleared by inquiry." } });
    fireEvent.click(screen.getByRole("button", { name: "Disable entry", ...inDialog }));
    await waitFor(() => expect(api.disable).toHaveBeenCalledWith("w1", "Cleared by inquiry."));
  });

  it("expires an entry after confirmation", async () => {
    api.expire.mockResolvedValue({ ...ENTRY, status: "EXPIRED" });
    render(<WatchlistManager />);
    fireEvent.click(await screen.findByRole("button", { name: "Expire Ali Khan" }));
    fireEvent.click(screen.getByRole("button", { name: "Expire now", ...inDialog }));
    await waitFor(() => expect(api.expire).toHaveBeenCalledWith("w1"));
    expect(await screen.findByText(/Entry expired/)).toBeTruthy();
  });

  it("offers no actions on disabled entries", async () => {
    api.list.mockResolvedValue({ items: [{ ...ENTRY, status: "DISABLED", disabled_reason: "Resolved.",
      disabled_at: "2026-09-02T08:00:00Z", disabled_by: { id: "u1", name: "Admin" } }], next_cursor: null });
    render(<WatchlistManager />);
    const row = await screen.findByTestId("watchlist-row");
    expect(row.textContent).toMatch(/Disabled.*by Admin: Resolved\./);
    expect(within(row).queryByRole("button")).toBeNull();
  });
});

describe("endOfDayIso", () => {
  it("is the last second of that day in the browser's time zone", () => {
    const end = new Date(endOfDayIso("2026-06-30"));
    expect([end.getFullYear(), end.getMonth(), end.getDate(), end.getHours(), end.getMinutes()]).toEqual([2026, 5, 30, 23, 59]);
  });
});
