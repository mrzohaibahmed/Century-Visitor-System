import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { arrival } from "@/test-utils/notifications";

const api = { list: vi.fn(), read: vi.fn(), readAll: vi.fn() };
vi.mock("@/lib/api/notifications", async (original) => ({
  ...(await original<typeof import("@/lib/api/notifications")>()),
  listNotifications: (...a: unknown[]) => api.list(...a),
  markNotificationRead: (...a: unknown[]) => api.read(...a),
  markAllNotificationsRead: (...a: unknown[]) => api.readAll(...a),
}));

const { NotificationList } = await import("./NotificationList");

beforeEach(() => Object.values(api).forEach((fn) => fn.mockReset()));
afterEach(cleanup);

describe("NotificationList", () => {
  it("lists notifications, loads more, and can show unread ones only", async () => {
    api.list.mockResolvedValueOnce({ items: [arrival("n1", "Ali Khan")], next_cursor: "c1", unread_count: 2 })
      .mockResolvedValueOnce({ items: [arrival("n2", "Alia Noor")], next_cursor: null, unread_count: 2 })
      .mockResolvedValue({ items: [arrival("n1", "Ali Khan")], next_cursor: null, unread_count: 2 });
    render(<NotificationList />);
    const name = await screen.findByText("Ali Khan");
    expect(name.parentElement?.textContent).toBe("Ali Khan has arrived to visit Sara Ahmed.");
    expect(name.classList.contains("caps")).toBe(true);                          // names shown in capitals
    fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    expect((await screen.findByText("Alia Noor")).parentElement?.textContent).toBe("Alia Noor has arrived to visit Sara Ahmed.");
    expect(api.list).toHaveBeenLastCalledWith({ cursor: "c1", unreadOnly: false });
    fireEvent.click(screen.getByLabelText("Unread only"));
    await waitFor(() => expect(api.list).toHaveBeenLastCalledWith({ cursor: null, unreadOnly: true }));
  });

  it("marks read and marks all as read", async () => {
    api.list.mockResolvedValue({ items: [arrival("n1", "Ali Khan")], next_cursor: null, unread_count: 1 });
    api.read.mockResolvedValue(arrival("n1", "Ali Khan", true));
    api.readAll.mockResolvedValue({ marked: 0, unread_count: 0 });
    render(<NotificationList />);
    fireEvent.click(await screen.findByRole("button", { name: /Unread: Visitor arrived/ }));
    await waitFor(() => expect(screen.getByRole("button", { name: /^Visitor arrived/ })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "Mark all as read" }));
    await waitFor(() => expect(api.readAll).toHaveBeenCalled());
  });

  it("says when there is nothing", async () => {
    api.list.mockResolvedValue({ items: [], next_cursor: null, unread_count: 0 });
    render(<NotificationList />);
    expect(await screen.findByText("No notifications.")).toBeTruthy();
  });
});
