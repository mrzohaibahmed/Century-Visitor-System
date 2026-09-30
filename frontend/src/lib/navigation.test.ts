import { describe, expect, it } from "vitest";

import { navItemsFor, sectionTitle } from "./navigation";

describe("navigation", () => {
  it("lists Gate cameras for administrators only", () => {
    expect(navItemsFor("ADMIN").find((i) => i.href === "/gate-cameras")).toMatchObject({ label: "Gate cameras", group: "admin" });
    expect(navItemsFor("GUARD").some((i) => i.href === "/gate-cameras")).toBe(false);
    expect(navItemsFor("GUARD").some((i) => i.group === "admin")).toBe(false);
  });

  it("lists Email settings for administrators only", () => {
    expect(navItemsFor("ADMIN").find((i) => i.href === "/settings/email")).toMatchObject({ label: "Email settings", group: "admin" });
    expect(navItemsFor("GUARD").some((i) => i.href.startsWith("/settings"))).toBe(false);
    expect(sectionTitle("/settings/email")).toBe("Email settings");
  });

  it("lists Reports for administrators only", () => {
    expect(navItemsFor("ADMIN").find((i) => i.href === "/reports")).toMatchObject({ label: "Reports", group: "admin" });
    expect(navItemsFor("GUARD").some((i) => i.href.startsWith("/reports"))).toBe(false);
    expect(sectionTitle("/reports")).toBe("Reports");
  });

  it("names the page in the top bar", () => {
    expect(sectionTitle("/gate-cameras")).toBe("Gate cameras");
  });
});
