import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/client";
import type { Overview, ReportRange, VisitReportRow } from "@/lib/api/reports";

const api = {
  getOverview: vi.fn(), getVisitReport: vi.fn(), getVisitorReport: vi.fn(), getHostReport: vi.fn(),
  getDepartmentReport: vi.fn(), getGuardReport: vi.fn(), getInsideReport: vi.fn(), getDenialReport: vi.fn(),
  downloadReportCsv: vi.fn(),
};
vi.mock("@/lib/api/reports", async (original) => {
  const actual = await original<typeof import("@/lib/api/reports")>();
  return { ...actual, ...Object.fromEntries(Object.keys(api).map((k) => [k, (...a: unknown[]) => api[k as keyof typeof api](...a)])) };
});
vi.mock("@/lib/api/directory", () => ({
  listGates: vi.fn(async () => [{ id: "g1", name: "Main Gate", location: null, is_active: true }]),
  listDepartments: vi.fn(async () => [{ id: "d1", name: "HR", notification_email: null, is_active: true }]),
  listHosts: vi.fn(async () => [{ id: "h1", name: "Sara Ahmed", department_name: "HR" }]),
}));
vi.mock("@/lib/api/users", () => ({
  listUsers: vi.fn(async () => ({ items: [{ id: "u1", username: "guard1", display_name: "Guard One" }] })),
}));
const toast = { success: vi.fn() };
vi.mock("sonner", () => ({ toast }));

const { ReportsWorkspace } = await import("./ReportsWorkspace");

const CNIC = "35201-1234567-1";
const RANGE: ReportRange = { preset: "today", from: "2026-09-30", to: "2026-09-30", timezone: "Asia/Karachi" };
const ref = (id: string, name: string) => ({ id, name });

function overview(visits = 12): Overview {
  return {
    range: RANGE, generated_at: "2026-09-30T10:00:00Z",
    totals: { visits, unique_visitors: 9, inside_now: 3, checked_out: 8, denied_entries: 2, watchlist_matches: 1,
              avg_duration_minutes: 75 },
    series: {
      bucket: "hour",
      over_time: Array.from({ length: 24 }, (_, h) => ({ start: `2026-09-30T${String(h).padStart(2, "0")}:00:00+05:00`,
                                                           count: h === 10 ? visits : 0 })),
      by_department: visits ? [{ id: "d1", name: "HR", count: visits }] : [],
      by_status: [{ status: "CHECKED_IN", count: 3 }, { status: "CHECKED_OUT", count: visits - 3 }],
      peak_hours: Array.from({ length: 24 }, (_, h) => ({ hour: h, count: h === 10 ? visits : 0 })),
    },
  };
}

function row(n: number, overrides: Partial<VisitReportRow> = {}): VisitReportRow {
  return {
    id: `v${n}`, visit_number: `V-2026-00000${n}`, visitor: ref(`p${n}`, `Visitor ${n}`), id_type: "CNIC",
    id_number: "***********67-1", phone: "*******4567", host: ref("h1", "Sara Ahmed"), host_unlisted: false,
    department: ref("d1", "HR"), reason_code: "INTERVIEW", reason_note: "private note", gate: ref("g1", "Main Gate"),
    check_in_at: "2026-09-30T05:00:00Z", check_out_at: null, duration_minutes: 95, status: "CHECKED_IN",
    checked_in_by: ref("u1", "Guard One"), checked_out_by: null, ...overrides,
  };
}

function openTab(name: string) {
  fireEvent.click(screen.getByRole("tab", { name }));
}

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  toast.success.mockReset();
  api.getOverview.mockResolvedValue(overview());
  api.getVisitReport.mockResolvedValue({ range: RANGE, total: 2, next_cursor: "c2", items: [row(1), row(2)] });
  api.getVisitorReport.mockResolvedValue({ range: RANGE, total: 1, next_cursor: null, items: [{
    visitor: ref("p1", "Ali Khan"), id_type: "CNIC", id_number: "***********67-1", phone: "*******4567", visits: 3,
    completed_visits: 2, first_visit_at: "2026-09-01T05:00:00Z", last_visit_at: "2026-09-29T05:00:00Z",
    avg_duration_minutes: 60, inside_now: true }] });
  api.getHostReport.mockResolvedValue({ range: RANGE, total: 1, truncated: false, items: [{
    host: ref(null as unknown as string, "Imran Ali"), host_unlisted: true, department: ref("d1", "HR"), visits: 4,
    completed_visits: 3, inside_now: 1 }] });
  api.getDepartmentReport.mockResolvedValue({ range: RANGE, total: 1, truncated: false, items: [{
    department: ref("d1", "HR"), visits: 4, completed_visits: 3, unique_visitors: 4, avg_duration_minutes: 30,
    inside_now: 1 }] });
  api.getGuardReport.mockResolvedValue({ range: RANGE, total: 1, truncated: false, items: [{
    guard: { id: "u1", name: "Guard One", role: "GUARD", is_active: true }, check_ins: 5, check_outs: 4, inside_now: 1,
    denied_entries: 2, watchlist_matches: 1 }] });
  api.getInsideReport.mockResolvedValue({ generated_at: "2026-09-30T10:00:00Z", total: 1, next_cursor: null,
                                          items: [row(7, { duration_minutes: 4 * 24 * 60 })] });
  api.getDenialReport.mockResolvedValue({ range: RANGE, total: 1, denied_entries: 2, watchlist_matches: 1,
    next_cursor: null, items: [{ id: "x1", at: "2026-09-30T06:00:00Z", reason: "WATCHLIST", reason_code: "DELIVERY",
      source: "lookup", visitor: ref("p1", "Ali Khan"), identifier: "CNIC:***********67-1",
      watchlist: { id: "w1", reason: "Theft of property." }, gate: ref("g1", "Main Gate"), operator: ref(null as unknown as string, "oldguard"),
      current_names: ["visitor"] }] });
});
afterEach(cleanup);

describe("Reports overview", () => {
  it("shows the server's totals and charts for today", async () => {
    render(<ReportsWorkspace />);
    expect((await screen.findByTestId("total-visits")).textContent).toBe("12");
    expect(screen.getByTestId("inside-now").textContent).toBe("3");
    expect(screen.getByTestId("denied").textContent).toBe("2");
    expect(screen.getByTestId("watchlist").textContent).toBe("1");        // a separate figure, not assumed equal
    expect(screen.getByTestId("avg-duration").textContent).toBe("1 h 15 min");
    expect(api.getOverview).toHaveBeenCalledTimes(1);
    expect(api.getOverview.mock.calls[0][0]).toEqual({ range: "today" });
    expect(screen.getByRole("img", { name: /Visits over time: 12 visits in total; the most, 12, at 30 Sept? 2026 10:00/ })).toBeTruthy();
    expect(screen.getByRole("list", { name: "Visits by department" }).textContent).toContain("HR");
    await waitFor(() => expect(screen.getByTestId("active-period").textContent).toMatch(/30 Sept? 2026 \(Asia\/Karachi\)/));
  });

  it("says so when the period has no visits", async () => {
    api.getOverview.mockResolvedValue(overview(0));
    render(<ReportsWorkspace />);
    expect((await screen.findAllByText("No visits in this reporting period.")).length).toBe(4);
  });

  it("asks again for a preset or a custom range", async () => {
    render(<ReportsWorkspace />);
    await screen.findByTestId("total-visits");
    fireEvent.click(screen.getByLabelText("This week"));
    await waitFor(() => expect(api.getOverview).toHaveBeenLastCalledWith({ range: "this_week" }, expect.anything()));
    fireEvent.click(screen.getByLabelText("Custom"));
    expect(api.getOverview).toHaveBeenCalledTimes(2);                    // nothing sent until "Apply"
    fireEvent.change(screen.getByLabelText("From"), { target: { value: "2026-09-01" } });
    fireEvent.change(screen.getByLabelText("To"), { target: { value: "2026-09-15" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    await waitFor(() => expect(api.getOverview).toHaveBeenLastCalledWith(
      { range: "custom", from: "2026-09-01", to: "2026-09-15" }, expect.anything()));
  });

  it("refuses a custom range that ends before it starts", async () => {
    render(<ReportsWorkspace />);
    fireEvent.click(screen.getByLabelText("Custom"));
    fireEvent.change(screen.getByLabelText("From"), { target: { value: "2026-09-15" } });
    fireEvent.change(screen.getByLabelText("To"), { target: { value: "2026-09-01" } });
    expect(screen.getByText("The start date is after the end date.")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Apply" }) as HTMLButtonElement).disabled).toBe(true);
  });
});

describe("Reports errors", () => {
  it("explains a refusal without offering a retry", async () => {
    api.getOverview.mockRejectedValue(new ApiError(403, "forbidden", "You do not have permission to do this."));
    render(<ReportsWorkspace />);
    expect(await screen.findByText("You do not have permission to view reports.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Try again/ })).toBeNull();
    expect(screen.queryByTestId("total-visits")).toBeNull();
  });

  it("offers a retry after a server or network failure, with a safe message", async () => {
    api.getOverview.mockRejectedValueOnce(new ApiError(500, "internal_error", "Traceback: KeyError 'x'"));
    render(<ReportsWorkspace />);
    expect(await screen.findByText("The report could not be loaded. Please try again in a moment.")).toBeTruthy();
    expect(screen.queryByText(/Traceback/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Try again/ }));
    expect((await screen.findByTestId("total-visits")).textContent).toBe("12");
    api.getOverview.mockRejectedValueOnce(new ApiError(0, "network_error", "Cannot reach the server."));
    fireEvent.click(screen.getByLabelText("Yesterday"));
    expect(await screen.findByText(/Check the network connection/)).toBeTruthy();
  });
});

describe("Visits report", () => {
  it("lists visits with masked values, filters, pages and exports what is shown", async () => {
    render(<ReportsWorkspace />);
    openTab("Visits");
    const rows = await screen.findAllByTestId("report-row");
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByTestId("masked-id").textContent).toBe("CNIC ***********67-1");
    expect(within(rows[0]).getByTestId("masked-phone").textContent).toBe("*******4567");
    expect(document.body.textContent).not.toContain(CNIC);
    expect(document.body.textContent).not.toContain("private note");          // reason notes are not shown
    expect(document.body.textContent).not.toContain("[object Object]");
    expect(screen.getByText("Showing 2 of 2")).toBeTruthy();

    // Load more: the next page along the server's cursor.
    api.getVisitReport.mockResolvedValueOnce({ range: RANGE, total: 3, next_cursor: null, items: [row(3)] });
    fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    await waitFor(() => expect(screen.getAllByTestId("report-row")).toHaveLength(3));
    expect(api.getVisitReport.mock.calls.at(-1)?.[2]).toBe("c2");

    // Filters are sent as chosen, on "Apply".
    fireEvent.change(screen.getByLabelText("Search"), { target: { value: "alia" } });
    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "CHECKED_OUT" } });
    fireEvent.change(await screen.findByLabelText("Purpose"), { target: { value: "DELIVERY" } });
    await screen.findByRole("option", { name: "Main Gate" });
    fireEvent.change(screen.getByLabelText("Gate"), { target: { value: "g1" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));
    await waitFor(() => expect(api.getVisitReport.mock.calls.at(-1)?.[1]).toMatchObject(
      { q: "alia", status: "CHECKED_OUT", reason_code: "DELIVERY", gate_id: "g1", sort: "check_in_desc" }));
    expect(api.getVisitReport.mock.calls.at(-1)?.[2]).toBeNull();          // a new search starts at page one

    // The export asks the server for exactly these filters and this range.
    api.downloadReportCsv.mockResolvedValue("century-gate-visits-2026-09-30.csv");
    fireEvent.click(screen.getByRole("button", { name: "Export CSV" }));
    await waitFor(() => expect(api.downloadReportCsv).toHaveBeenCalledWith(
      "visits", { range: "today" }, expect.objectContaining({ q: "alia", status: "CHECKED_OUT", gate_id: "g1" })));
    expect(toast.success).toHaveBeenCalledWith("Downloaded century-gate-visits-2026-09-30.csv");
  });

  it("shows why an export failed", async () => {
    api.downloadReportCsv.mockRejectedValue(new ApiError(422, "export_too_large", "Choose a shorter date range."));
    render(<ReportsWorkspace />);
    openTab("Visits");
    await screen.findAllByTestId("report-row");
    fireEvent.click(screen.getByRole("button", { name: "Export CSV" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Choose a shorter date range.");
  });

  it("says so when nothing matches", async () => {
    api.getVisitReport.mockResolvedValue({ range: RANGE, total: 0, next_cursor: null, items: [] });
    render(<ReportsWorkspace />);
    openTab("Visits");
    expect(await screen.findByText("No visits found for this reporting period.")).toBeTruthy();
  });
});

describe("Other reports", () => {
  it("shows the visitor summary", async () => {
    render(<ReportsWorkspace />);
    openTab("Visitors");
    const [r] = await screen.findAllByTestId("report-row");
    expect(r.textContent).toContain("Ali Khan");
    expect(within(r).getByTestId("masked-id").textContent).toBe("CNIC ***********67-1");
    expect(r.textContent).toContain("Inside");
  });

  it("shows hosts and departments side by side, each with its export", async () => {
    render(<ReportsWorkspace />);
    openTab("Hosts & departments");
    expect(await screen.findByText("Imran Ali")).toBeTruthy();
    expect(screen.getByText("(not listed)")).toBeTruthy();
    expect(within(screen.getByRole("table", { name: "Visits per department" })).getByText("HR")).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "Export CSV" })).toHaveLength(2);
  });

  it("shows operators without any account data", async () => {
    render(<ReportsWorkspace />);
    openTab("Guards");
    const [r] = await screen.findAllByTestId("report-row");
    expect(r.textContent).toContain("Guard One");
    expect(document.body.textContent?.toLowerCase()).not.toMatch(/password|session|token/);
  });

  it("shows who is inside now, whatever the period, and exports without a range", async () => {
    render(<ReportsWorkspace />);
    openTab("Currently inside");
    const [r] = await screen.findAllByTestId("report-row");
    expect(r.textContent).toContain("4 d 0 h");
    expect(api.getInsideReport).toHaveBeenCalledTimes(1);
    expect(api.getInsideReport.mock.calls[0][0]).toMatchObject({ sort: "check_in_asc" });
    expect(screen.getByTestId("active-period").textContent).toContain("does not apply");
    api.downloadReportCsv.mockResolvedValue("century-gate-inside.csv");
    fireEvent.click(screen.getByRole("button", { name: "Export CSV" }));
    await waitFor(() => expect(api.downloadReportCsv).toHaveBeenCalledWith("inside", null, expect.anything()));
  });

  it("keeps denied entries and watchlist matches apart", async () => {
    render(<ReportsWorkspace />);
    openTab("Security");
    expect((await screen.findByTestId("denied-entries")).textContent).toBe("2");
    expect(screen.getByTestId("watchlist-matches").textContent).toBe("1");
    const [r] = screen.getAllByTestId("report-row");
    expect(r.textContent).toContain("At the ID lookup");
    expect(r.textContent).toContain("Theft of property.");
    expect(r.textContent).toContain("(current name)");
    expect(within(r).getByTestId("masked-id").textContent).toBe("CNIC:***********67-1");
    expect(document.body.textContent).not.toContain(CNIC);
  });
});
