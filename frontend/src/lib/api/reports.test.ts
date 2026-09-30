import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "./client";

const client = { apiBlob: vi.fn(), apiRequest: vi.fn() };
vi.mock("./client", async (original) => ({
  ...(await original<typeof import("./client")>()),
  apiBlob: (...a: unknown[]) => client.apiBlob(...a),
  apiRequest: (...a: unknown[]) => client.apiRequest(...a),
}));

const reports = await import("./reports");

beforeEach(() => {
  client.apiBlob.mockReset();
  client.apiRequest.mockReset().mockResolvedValue({});
});
afterEach(() => vi.unstubAllGlobals());

describe("report requests", () => {
  it("sends presets as they are: the server works out the days", async () => {
    await reports.getOverview({ range: "this_week" });
    expect(client.apiRequest).toHaveBeenCalledWith("/reports/overview?range=this_week", expect.anything());
  });

  it("sends a custom range and only the filters that are set", async () => {
    await reports.getVisitReport({ range: "custom", from: "2026-09-01", to: "2026-09-30" },
      { q: " alia ", status: "", host_id: "h1", reason_code: "DELIVERY", sort: "check_in_desc" }, "c1");
    expect(client.apiRequest.mock.calls[0][0]).toBe(
      "/reports/visits?range=custom&from=2026-09-01&to=2026-09-30&q=alia&host_id=h1&reason_code=DELIVERY"
      + "&sort=check_in_desc&cursor=c1&limit=25");
  });

  it("ignores stray dates on a preset", () => {
    expect(reports.reportQuery({ range: "today", from: "2026-01-01", to: "2026-01-02" })).toBe("?range=today");
  });

  it("asks for the inside report without any range: it is the current state", async () => {
    await reports.getInsideReport({ q: "", sort: "check_in_asc" }, null);
    expect(client.apiRequest.mock.calls[0][0]).toBe("/reports/inside?sort=check_in_asc&limit=25");
  });
});

describe("CSV export", () => {
  function stubDownload() {
    const createObjectURL = vi.fn(() => "blob:report");
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL, revokeObjectURL: vi.fn() }));
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    return { createObjectURL, click };
  }

  it("downloads the server's file for the current range and filters", async () => {
    const { click } = stubDownload();
    const blob = new Blob(["Visit number\r\n"], { type: "text/csv" });
    client.apiBlob.mockResolvedValue({
      blob, headers: new Headers({ "content-type": "text/csv; charset=utf-8",
                                   "content-disposition": 'attachment; filename="century-gate-visits-2026-09-30.csv"' }) });
    const name = await reports.downloadReportCsv("visits", { range: "yesterday" }, { status: "CHECKED_IN", q: "" });
    expect(client.apiBlob).toHaveBeenCalledWith("/reports/visits/export?range=yesterday&status=CHECKED_IN&format=csv",
                                                {}, "text/csv, application/json");
    expect(name).toBe("century-gate-visits-2026-09-30.csv");
    expect(click).toHaveBeenCalledOnce();
  });

  it("never uses a file name it does not trust", () => {
    expect(reports.fileNameFrom('attachment; filename="../../evil.exe"', "visits")).toBe("century-gate-visits.csv");
    expect(reports.fileNameFrom(null, "denials")).toBe("century-gate-denials.csv");
  });

  it("passes the server's errors on", async () => {
    client.apiBlob.mockRejectedValue(new ApiError(422, "export_too_large", "Choose a shorter date range."));
    await expect(reports.downloadReportCsv("visits", { range: "this_month" })).rejects.toMatchObject({ code: "export_too_large" });
  });

  it("refuses an answer that is not a CSV file", async () => {
    stubDownload();
    client.apiBlob.mockResolvedValue({ blob: new Blob(["{}"]), headers: new Headers({ "content-type": "application/json" }) });
    await expect(reports.downloadReportCsv("visits", { range: "today" })).rejects.toBeInstanceOf(ApiError);
  });
});
