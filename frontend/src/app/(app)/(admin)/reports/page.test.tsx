import { afterEach, describe, expect, it, vi } from "vitest";

const session = vi.fn();
const redirect = vi.fn((to: string) => { throw new Error(`redirect:${to}`); });
vi.mock("@/lib/api/server", () => ({ getServerSession: () => session() }));
vi.mock("next/navigation", () => ({ redirect: (to: string) => redirect(to) }));
vi.mock("./ReportsWorkspace", () => ({ ReportsWorkspace: () => null }));

const { default: ReportsPage } = await import("./page");

afterEach(() => { session.mockReset(); redirect.mockClear(); });

describe("Reports page access", () => {
  it("renders for a user holding reports:view", async () => {
    session.mockResolvedValue({ user: { role: "ADMIN" }, permissions: ["reports:view", "reports:export"] });
    expect(await ReportsPage()).toBeTruthy();
    expect(redirect).not.toHaveBeenCalled();
  });

  it("sends anyone else away before rendering anything", async () => {
    session.mockResolvedValue({ user: { role: "GUARD" }, permissions: ["visit:read"] });
    await expect(ReportsPage()).rejects.toThrow("redirect:/dashboard");
    session.mockResolvedValue(null);
    await expect(ReportsPage()).rejects.toThrow("redirect:/login");
  });
});
