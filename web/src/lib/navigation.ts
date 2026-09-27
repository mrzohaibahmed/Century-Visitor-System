/**
 * Sidebar entries. Only pages that exist are listed; each later phase adds its
 * pages here. `roles` is used to HIDE entries a role cannot use; the backend
 * enforces the actual permissions (Phase 2).
 */
export type Role = "ADMIN" | "GUARD";

export type NavItem = {
  href: string;
  label: string;
  roles: Role[];
};

export const NAV_ITEMS: NavItem[] = [
  { href: "/dashboard", label: "Dashboard", roles: ["ADMIN", "GUARD"] },
];
