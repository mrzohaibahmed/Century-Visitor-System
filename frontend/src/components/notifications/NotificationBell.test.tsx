import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/client";
import { timeAgo } from "@/lib/api/notifications";
import { arrival } from "@/test-utils/notifications";

const api = { list: vi.fn(), read: vi.fn(), readAll: vi.fn() };
vi.mock("@/lib/api/notifications", async (original) => ({
  ...(await original<typeof import("@/lib/api/notifications")>()),
  listNotifications: (...a: unknown[]) => api.list(...a),
  markNotificationRead: (...a: unknown[]) => api.read(...a),
  markAllNotificationsRead: (...a: unknown[]) => api.readAll(...a),
}));

const { NotificationBell } = await import("./NotificationBell");

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
});
afterEach(() => { cleanup(); vi.useRealTimers(); });

function openBell() {
  fireEvent.click(screen.getByRole("button", { name: /^Notifications/ }));
}

describe("NotificationBell", () => {
  it("shows the unread count from the server and lists recent notifications", async () => {
    api.list.mockResolvedValue({ items: [arrival("n1", "Ali Khan"), arrival("n2", "Alia Noor", true)],
                                 next_cursor: null, unread_count: 7 });
    render(<NotificationBell />);
    expect((await screen.findByTestId("notification-count")).textContent).toBe("7");       // not the list length
    expect(screen.getByRole("button", { name: "Notifications, 7 unread" })).toBeTruthy();
    openBell();
    const items = await screen.findAllByTestId("notification-item");
    expect(items).toHaveLength(2);
    expect(items[0].textContent).toMatch(/Visitor arrived.*Ali Khan has arrived to visit Sara Ahmed\..*Main Gate · HR · 2 minutes ago · Host e-mailed/);
    expect(screen.getByRole("link", { name: "View all" }).getAttribute("href")).toBe("/notifications");
  });

  it("marks one notification read when it is clicked", async () => {
    api.list.mockResolvedValue({ items: [arrival("n1", "Ali Khan")], next_cursor: null, unread_count: 1 });
    api.read.mockResolvedValue(arrival("n1", "Ali Khan", true));
    render(<NotificationBell />);
    openBell();
    fireEvent.click(await screen.findByRole("button", { name: /Unread: Visitor arrived/ }));
    await waitFor(() => expect(api.read).toHaveBeenCalledWith("n1"));
    await waitFor(() => expect(screen.queryByTestId("notification-count")).toBeNull());
    fireEvent.click(screen.getByRole("button", { name: /^Visitor arrived/ }));                // already read: no call
    expect(api.read).toHaveBeenCalledTimes(1);
  });

  it("marks all as read and reloads the count from the server", async () => {
    let allRead = false;
    api.list.mockImplementation(async () => ({
      items: [arrival("n1", "Ali Khan", allRead), arrival("n2", "Alia Noor", allRead)], next_cursor: null,
      unread_count: allRead ? 0 : 2 }));
    api.readAll.mockImplementation(async () => { allRead = true; return { marked: 2, unread_count: 0 }; });
    render(<NotificationBell />);
    expect(await screen.findByTestId("notification-count")).toBeTruthy();
    openBell();
    fireEvent.click(await screen.findByRole("button", { name: "Mark all as read" }));
    await waitFor(() => expect(api.readAll).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByTestId("notification-count")).toBeNull());
  });

  it("shows loading, empty and failure states", async () => {
    let resolve: (v: unknown) => void = () => {};
    api.list.mockReturnValueOnce(new Promise((r) => { resolve = r; }));
    render(<NotificationBell />);
    openBell();
    expect(screen.getByText("Loading…")).toBeTruthy();
    await act(async () => resolve({ items: [], next_cursor: null, unread_count: 0 }));
    expect(await screen.findByText("No notifications yet.")).toBeTruthy();
    cleanup();

    api.list.mockRejectedValue(new ApiError(0, "network_error", "Cannot reach the server."));
    render(<NotificationBell />);
    openBell();
    expect((await screen.findByRole("alert")).textContent).toContain("Cannot reach the server.");
  });

  it("polls while the page is visible", async () => {
    vi.useFakeTimers();
    api.list.mockResolvedValue({ items: [], next_cursor: null, unread_count: 0 });
    render(<NotificationBell />);
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    expect(api.list).toHaveBeenCalledTimes(2);
  });
});

describe("timeAgo", () => {
  const now = new Date("2026-09-27T10:00:00Z");
  it.each([["2026-09-27T09:59:40Z", "just now"], ["2026-09-27T09:58:00Z", "2 minutes ago"],
           ["2026-09-27T09:59:00Z", "1 minute ago"], ["2026-09-27T07:00:00Z", "3 hours ago"]])("%s → %s", (iso, text) => {
    expect(timeAgo(iso, now)).toBe(text);
  });
});
