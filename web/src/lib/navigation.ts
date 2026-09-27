/**
 * Sidebar entries. Only pages that exist are listed; each later phase adds its
 * pages here. `roles` only HIDES entries a role cannot use; the API enforces
 * the actual permissions on every request.
 */
import type { Role } from "@/lib/api/auth";

export type NavItem = {
  href: string;
  label: string;
  roles: Role[];
};

export const NAV_ITEMS: NavItem[] = [
  { href: "/dashboard", label: "Dashboard", roles: ["ADMIN", "GUARD"] },
  { href: "/users", label: "Users", roles: ["ADMIN"] },
];

export function navItemsFor(role: Role): NavItem[] {
  return NAV_ITEMS.filter((item) => item.roles.includes(role));
}
