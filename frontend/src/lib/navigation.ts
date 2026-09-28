/**
 * Sidebar entries. Only pages that exist are listed; each later phase adds its
 * pages here. `roles` only HIDES entries a role cannot use; the API enforces
 * the actual permissions on every request.
 */
import type { Role } from "@/lib/api/auth";

export type NavGroup = "front-desk" | "admin";

export type NavItem = {
  href: string;
  label: string;
  roles: Role[];
  group: NavGroup;
};

const EVERYONE: Role[] = ["ADMIN", "GUARD"];

export const NAV_GROUPS: { id: NavGroup; label: string }[] = [
  { id: "front-desk", label: "Front desk" },
  { id: "admin", label: "Administration" },
];

export const NAV_ITEMS: NavItem[] = [
  { href: "/dashboard", label: "Dashboard", roles: EVERYONE, group: "front-desk" },
  { href: "/check-in", label: "Check in", roles: EVERYONE, group: "front-desk" },
  { href: "/check-out", label: "Check out", roles: EVERYONE, group: "front-desk" },
  { href: "/visitors", label: "Visitors", roles: EVERYONE, group: "front-desk" },
  { href: "/visits", label: "Visit history", roles: EVERYONE, group: "front-desk" },
  { href: "/notifications", label: "Notifications", roles: EVERYONE, group: "front-desk" },
  { href: "/watchlist", label: "Watchlist", roles: ["ADMIN"], group: "admin" },
  { href: "/directory/hosts", label: "Hosts", roles: ["ADMIN"], group: "admin" },
  { href: "/directory/departments", label: "Departments", roles: ["ADMIN"], group: "admin" },
  { href: "/directory/gates", label: "Gates", roles: ["ADMIN"], group: "admin" },
  { href: "/users", label: "Users", roles: ["ADMIN"], group: "admin" },
];

export function navItemsFor(role: Role): NavItem[] {
  return NAV_ITEMS.filter((item) => item.roles.includes(role));
}

export function isActive(item: NavItem, pathname: string): boolean {
  return pathname === item.href || pathname.startsWith(`${item.href}/`);
}

/** The section name shown in the top bar for the current page. */
export function sectionTitle(pathname: string): string {
  if (pathname.startsWith("/account/password")) return "Change password";
  return NAV_ITEMS.find((item) => isActive(item, pathname))?.label ?? "Century Gate";
}
