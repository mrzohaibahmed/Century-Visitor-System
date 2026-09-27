import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/client";
import type { IssuedPass } from "@/lib/api/passes";

const api = { recordBadgePrint: vi.fn() };
vi.mock("@/lib/api/passes", async (original) => ({
  ...(await original<typeof import("@/lib/api/passes")>()),
  recordBadgePrint: (...a: unknown[]) => api.recordBadgePrint(...a),
}));

const { BadgePreview } = await import("./VisitorBadge");

export const ISSUED: IssuedPass = {
  qr_text: `CGP1:${"0123456789ABCDEF".repeat(4)}`, expires_at: "2026-09-28T08:00:00Z",
  badge: { organization: "Century Gate", visitor_name: "Ali Khan", visit_number: "V-2026-000042",
           host_name: "Sara Ahmed", department_name: "HR", gate_name: "Main Gate",
           check_in_at: "2026-09-27T08:00:00Z", valid_until: "2026-09-28T08:00:00Z" },
};

beforeEach(() => {
  api.recordBadgePrint.mockReset();
  window.print = vi.fn();
});
afterEach(cleanup);

describe("BadgePreview", () => {
  it("shows the gate information and a QR code, never an ID number", async () => {
    render(<BadgePreview issued={ISSUED} visitId="visit1" />);
    const card = screen.getByTestId("badge-card");
    expect(card.textContent).toMatch(/Century Gate.*VISITOR.*Ali Khan.*V-2026-000042.*Sara Ahmed.*HR.*Main Gate/);
    expect(card.textContent).not.toMatch(/35201|CNIC|CGP1/);
    const qr = await screen.findByTestId("badge-qr");
    expect(qr.getAttribute("src")).toMatch(/^data:image\/png;base64,/);
  });

  it("renders a separate copy that is the only thing printed", async () => {
    const { unmount } = render(<BadgePreview issued={ISSUED} visitId="visit1" />);
    const root = document.body.querySelector(":scope > .badge-print-root");
    expect(root?.textContent).toContain("V-2026-000042");
    unmount();
    expect(document.body.querySelector(".badge-print-root")).toBeNull();          // removed with the badge
  });

  it("records the print, then opens the print dialog", async () => {
    api.recordBadgePrint.mockResolvedValue(undefined);
    render(<BadgePreview issued={ISSUED} visitId="visit1" />);
    await screen.findByTestId("badge-qr");
    fireEvent.click(screen.getByRole("button", { name: "Print badge" }));
    await waitFor(() => expect(window.print).toHaveBeenCalled());
    expect(api.recordBadgePrint).toHaveBeenCalledWith("visit1");
  });

  it("does not print when the print cannot be recorded", async () => {
    api.recordBadgePrint.mockRejectedValue(new ApiError(0, "network_error", "Cannot reach the server."));
    render(<BadgePreview issued={ISSUED} visitId="visit1" />);
    await screen.findByTestId("badge-qr");
    fireEvent.click(screen.getByRole("button", { name: "Print badge" }));
    expect(await screen.findByText("Cannot reach the server.")).toBeTruthy();
    expect(window.print).not.toHaveBeenCalled();
  });
});
