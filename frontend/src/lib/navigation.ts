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

const EVERYONE: Role[] = ["ADMIN", "GUARD"];

export const NAV_ITEMS: NavItem[] = [
  { href: "/dashboard", label: "Dashboard", roles: EVERYONE },
  { href: "/check-in", label: "Check in", roles: EVERYONE },
  { href: "/check-out", label: "Check out", roles: EVERYONE },
  { href: "/visitors", label: "Visitors", roles: EVERYONE },
  { href: "/visits", label: "Visit history", roles: EVERYONE },
  { href: "/watchlist", label: "Watchlist", roles: ["ADMIN"] },
  { href: "/directory/hosts", label: "Hosts", roles: ["ADMIN"] },
  { href: "/directory/departments", label: "Departments", roles: ["ADMIN"] },
  { href: "/directory/gates", label: "Gates", roles: ["ADMIN"] },
  { href: "/users", label: "Users", roles: ["ADMIN"] },
];

export function navItemsFor(role: Role): NavItem[] {
  return NAV_ITEMS.filter((item) => item.roles.includes(role));
}
