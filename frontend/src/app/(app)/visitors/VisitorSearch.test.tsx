import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Visitor } from "@/lib/api/visitors";

const api = { searchVisitors: vi.fn() };
vi.mock("@/lib/api/visitors", async (original) => ({
  ...(await original<typeof import("@/lib/api/visitors")>()),
  searchVisitors: (...a: unknown[]) => api.searchVisitors(...a),
}));

const { VisitorSearch } = await import("./VisitorSearch");

function visitor(overrides: Partial<Visitor> = {}): Visitor {
  return {
    id: "v1", full_name: "Hamza Tariq", identity: { type: "CNIC", number: "35202-7654321-3" }, phone: "03001112223",
    created_at: "2026-09-27T08:00:00Z", updated_at: "2026-09-27T08:00:00Z", active_visit: null, photo_id: null, ...overrides,
  };
}

function search(q: string) {
  fireEvent.change(screen.getByLabelText("Search visitors"), { target: { value: q } });
  fireEvent.click(screen.getByRole("button", { name: "Search" }));
}

beforeEach(() => api.searchVisitors.mockReset());
afterEach(cleanup);

describe("VisitorSearch", () => {
  it("asks for a search first and needs at least 2 characters", () => {
    render(<VisitorSearch />);
    expect(screen.getByText("Search for a visitor")).toBeTruthy();
    search("h");
    expect(screen.getByText("Type at least 2 characters.")).toBeTruthy();
    expect(api.searchVisitors).not.toHaveBeenCalled();
  });

  it("shows a loading state, not a false 'no match', then links each visitor to their record", async () => {
    let resolve: (v: unknown) => void = () => {};
    api.searchVisitors.mockReturnValue(new Promise((r) => { resolve = r; }));
    render(<VisitorSearch />);
    search("hamza");
    expect(screen.getByText("Searching…")).toBeTruthy();
    expect(screen.queryByText(/No visitor matches/)).toBeNull();
    resolve({ items: [visitor(), visitor({ id: "v2", full_name: "Hamza Ali", phone: null })], next_cursor: null });
    const link = await screen.findByRole("link", { name: /Hamza Tariq/ });
    expect(link.getAttribute("href")).toBe("/visitors/v1");
    expect(link.textContent).toMatch(/35202-7654321-3.*03001112223/);
    // Search results carry no current visit, so the list makes no inside/not-inside claim.
    expect(link.textContent).not.toMatch(/inside/i);
    expect(screen.getByRole("link", { name: /Hamza Ali/ }).textContent).toMatch(/No phone/);
    expect(screen.getByText(/2 matches/)).toBeTruthy();
    expect(api.searchVisitors).toHaveBeenCalledWith("hamza", null);
  });

  it("says when nothing matches", async () => {
    api.searchVisitors.mockResolvedValue({ items: [], next_cursor: null });
    render(<VisitorSearch />);
    search("zzz");
    expect(await screen.findByText("No visitor matches “zzz”.")).toBeTruthy();
  });

  it("reports a failed search and retries it", async () => {
    api.searchVisitors.mockRejectedValueOnce(new Error("offline")).mockResolvedValue({ items: [visitor()], next_cursor: null });
    render(<VisitorSearch />);
    search("hamza");
    expect(await screen.findByText("Unable to search visitors")).toBeTruthy();
    expect(screen.queryByText(/No visitor matches/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("link", { name: /Hamza Tariq/ })).toBeTruthy();
  });

  it("loads the next page of matches", async () => {
    api.searchVisitors
      .mockResolvedValueOnce({ items: [visitor()], next_cursor: "c1" })
      .mockResolvedValueOnce({ items: [visitor({ id: "v2", full_name: "Hamza Ali" })], next_cursor: null });
    render(<VisitorSearch />);
    search("hamza");
    expect(await screen.findByText(/Showing the first 1 matches/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    await waitFor(() => expect(api.searchVisitors).toHaveBeenLastCalledWith("hamza", "c1"));
    expect(await screen.findByRole("link", { name: /Hamza Ali/ })).toBeTruthy();
  });
});
