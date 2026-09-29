import { describe, expect, it, vi } from "vitest";

// Admin pages (watchlist, directory, users, gate cameras) are guarded here, on the server, before
// anything renders; hiding the sidebar entries is only convenience. The API refuses guards too.
const session = { current: null as null | { user: { role: string } } };
vi.mock("@/lib/api/server", () => ({ getServerSession: async () => session.current }));
vi.mock("next/navigation", () => ({
  redirect: (to: string) => { throw new Error(`redirect:${to}`); },
}));

const { default: AdminLayout } = await import("./layout");

async function open(role: string | null) {
  session.current = role ? { user: { role } } : null;
  return AdminLayout({ children: "gate cameras page", params: Promise.resolve({}) } as never);
}

describe("AdminLayout", () => {
  it("renders admin pages for an administrator", async () => {
    expect(await open("ADMIN")).toBe("gate cameras page");
  });

  it("sends a guard to the dashboard without rendering the page", async () => {
    await expect(open("GUARD")).rejects.toThrow("redirect:/dashboard");
  });

  it("sends a signed-out visitor to the login page", async () => {
    await expect(open(null)).rejects.toThrow("redirect:/login");
  });
});
