import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Visit } from "@/lib/api/visits";

const api = { activeVisits: vi.fn(), listVisits: vi.fn() };
vi.mock("@/lib/api/visits", async (original) => ({
  ...(await original<typeof import("@/lib/api/visits")>()),
  activeVisits: (...a: unknown[]) => api.activeVisits(...a),
  listVisits: (...a: unknown[]) => api.listVisits(...a),
}));
vi.mock("@/components/session/SessionProvider", () => ({
  useSession: () => ({ user: { display_name: "Ayesha Khan", username: "ayesha", role: "GUARD" } }),
}));
vi.mock("./DashboardStatus", () => ({ DashboardStatus: () => null }));

const { Dashboard } = await import("./Dashboard");

const ref = (id: string, name: string) => ({ id, name });
let seq = 0;
function visit(overrides: Partial<Visit> = {}): Visit {
  seq += 1;
  return {
    id: `visit${seq}`, visit_number: `V-2026-${String(seq).padStart(6, "0")}`, status: "CHECKED_IN",
    visitor: ref(`v${seq}`, `Visitor ${seq}`), host: ref("h1", "Sara Ahmed"), host_unlisted: false,
    department: ref("d1", "HR"), gate: ref("g1", "Main Gate"), checkout_gate: null, reason_code: "INTERVIEW",
    reason_note: null, vehicle_registration: null, belongings: [], check_in_at: new Date().toISOString(),
    check_out_at: null, checked_in_by: ref("u1", "Guard"), checked_out_by: null, checkout_method: null, photo_id: null,
    ...overrides,
  };
}
const hoursAgo = (h: number) => new Date(Date.now() - h * 3600_000).toISOString();
const tile = (label: string) =>
  within(screen.getByRole("region", { name: "Today at a glance" })).getByText(label).closest("div")!.parentElement!;

beforeEach(() => { Object.values(api).forEach((fn) => fn.mockReset()); seq = 0; });
afterEach(cleanup);

describe("Dashboard", () => {
  it("counts today's visits across pages and flags long stays", async () => {
    const longStay = visit({ check_in_at: hoursAgo(9), visitor: ref("vx", "Kamran Long") });
    api.activeVisits.mockResolvedValue({ items: [visit(), longStay], total: 2 });
    api.listVisits
      .mockResolvedValueOnce({ items: [visit(), visit({ status: "CHECKED_OUT", check_out_at: hoursAgo(1) })], next_cursor: "c1" })
      .mockResolvedValueOnce({ items: [visit({ status: "CHECKED_OUT", check_out_at: hoursAgo(2) })], next_cursor: null });
    render(<Dashboard />);

    expect((await screen.findByTestId("inside-count")).textContent).toBe("2");
    expect(await within(tile("Checked in")).findByText("3")).toBeTruthy();
    expect(within(tile("Checked out")).getByText("2")).toBeTruthy();
    expect(within(tile("Stays over 8 h")).getByText("1")).toBeTruthy();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toMatch(/, Ayesha$/);

    // Pages of 100, following the cursor, for today's check-in day.
    expect(api.listVisits).toHaveBeenCalledTimes(2);
    const [filters, cursor, , limit] = api.listVisits.mock.calls[1];
    expect(filters).toEqual({ from: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/), to: filters.from });
    expect([cursor, limit]).toEqual(["c1", 100]);
    expect(screen.getAllByText("Kamran Long").length).toBeGreaterThan(0);   // listed under Alerts
  });

  it("stops at 500 visits and says so", async () => {
    api.activeVisits.mockResolvedValue({ items: [], total: 0 });
    api.listVisits.mockImplementation(async () => ({ items: Array.from({ length: 100 }, () => visit()), next_cursor: "more" }));
    render(<Dashboard />);
    expect(await within(tile("Checked in")).findByText("500+")).toBeTruthy();
    expect(api.listVisits).toHaveBeenCalledTimes(5);
    expect(screen.getByRole("link", { name: /View all 500\+ of today's visits/ }).getAttribute("href")).toBe("/visits");
  });

  it("shows an empty day and an unavailable server honestly", async () => {
    api.activeVisits.mockRejectedValue(new Error("Cannot reach the server."));
    api.listVisits.mockResolvedValue({ items: [], next_cursor: null });
    render(<Dashboard />);
    expect(await screen.findByText("No visitors today yet")).toBeTruthy();
    expect((await screen.findByTestId("inside-count")).textContent).toBe("—");
    expect(screen.getByText("Unable to load visitors inside")).toBeTruthy();
  });
});
