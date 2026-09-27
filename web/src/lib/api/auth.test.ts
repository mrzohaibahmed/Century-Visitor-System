import { describe, expect, it } from "vitest";

import { navItemsFor } from "@/lib/navigation";

import { safeNextPath } from "./auth";

describe("safeNextPath (no open redirects after login)", () => {
  it.each([
    ["/users", "/users"],
    ["/visitors/123?tab=visits", "/visitors/123?tab=visits"],
  ])("keeps same-site path %s", (input, expected) => {
    expect(safeNextPath(input)).toBe(expected);
  });

  it.each([null, undefined, "", "https://evil.example", "//evil.example", "/\\evil.example", "javascript:alert(1)",
    "/login?next=/users"])("falls back to the dashboard for %s", (input) => {
    expect(safeNextPath(input)).toBe("/dashboard");
  });
});

describe("navItemsFor", () => {
  it("shows administrators the user management page", () => {
    expect(navItemsFor("ADMIN").map((i) => i.href)).toContain("/users");
  });

  it("hides administration pages from guards", () => {
    expect(navItemsFor("GUARD").map((i) => i.href)).toEqual(["/dashboard"]);
  });
});
