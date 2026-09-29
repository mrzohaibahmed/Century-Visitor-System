"use client";

import {
  Bell, Building2, Cctv, Contact, DoorClosed, History, LayoutDashboard, LogIn, LogOut, type LucideIcon, Mail, ShieldAlert,
  UserCog, Users,
} from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useId } from "react";

import crest from "@/assets/century-crest.png";
import { Tooltip } from "@/components/ui/Tooltip";
import type { Role } from "@/lib/api/auth";
import { isActive, NAV_GROUPS, type NavItem, navItemsFor } from "@/lib/navigation";

const ICONS: Record<string, LucideIcon> = {
  "/dashboard": LayoutDashboard,
  "/check-in": LogIn,
  "/check-out": LogOut,
  "/visitors": Users,
  "/visits": History,
  "/notifications": Bell,
  "/watchlist": ShieldAlert,
  "/directory/hosts": Contact,
  "/directory/departments": Building2,
  "/directory/gates": DoorClosed,
  "/gate-cameras": Cctv,
  "/settings/email": Mail,
  "/users": UserCog,
};

export function Brand({ collapsed = false }: { collapsed?: boolean }) {
  return (
    <div className="flex min-w-0 items-center gap-3">
      {/* The Century crest on the brand navy, as on the login page (the same in both themes). */}
      <span aria-hidden="true"
            className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-linear-160 from-brand-900 to-navy-950 ring-1 ring-gold-400/30">
        <Image src={crest} alt="" sizes="36px" className="h-auto w-9" />
      </span>
      <span className={collapsed ? "sr-only" : "min-w-0 leading-tight"}>
        <span className="block truncate text-sm font-bold tracking-wide text-ink">Century Gate</span>
        <span className="block truncate text-xs text-ink-muted">Visitor Management</span>
      </span>
    </div>
  );
}

/** The main navigation, grouped; role-aware (the API still enforces every permission). */
export function SidebarNav({ role, collapsed = false, onNavigate }: {
  role: Role;
  collapsed?: boolean;
  onNavigate?: () => void;
}) {
  const pathname = usePathname();
  const items = navItemsFor(role);
  return (
    <nav aria-label="Main" className={collapsed ? "space-y-4 px-3 py-3" : "space-y-6 px-3 py-4"}>
      {NAV_GROUPS.map((group, index) => {
        const groupItems = items.filter((item) => item.group === group.id);
        if (groupItems.length === 0) return null;
        return (
          <NavSection key={group.id} label={group.label} collapsed={collapsed} divider={index > 0}>
            {groupItems.map((item) => (
              <li key={item.href}>
                <NavLink item={item} active={isActive(item, pathname)} collapsed={collapsed} onNavigate={onNavigate} />
              </li>
            ))}
          </NavSection>
        );
      })}
    </nav>
  );
}

function NavSection({ label, collapsed, divider, children }: {
  label: string;
  collapsed: boolean;
  divider: boolean;
  children: React.ReactNode;
}) {
  const id = useId();
  return (
    <div>
      {collapsed && divider && <div aria-hidden="true" className="mx-auto mb-4 h-px w-8 bg-border" />}
      <p id={id} className={collapsed ? "sr-only" : "px-3 pb-2 text-xs font-semibold tracking-wider text-ink-subtle uppercase"}>
        {label}
      </p>
      <ul aria-labelledby={id} className="space-y-1">{children}</ul>
    </div>
  );
}

function NavLink({ item, active, collapsed, onNavigate }: {
  item: NavItem;
  active: boolean;
  collapsed: boolean;
  onNavigate?: () => void;
}) {
  const Icon = ICONS[item.href] ?? LayoutDashboard;
  return (
    <Tooltip label={item.label} disabled={!collapsed}>
      <Link href={item.href} aria-current={active ? "page" : undefined} onClick={onNavigate}
            className={`relative flex min-h-11 items-center gap-3 rounded-xl text-sm transition-colors
              ${collapsed ? "w-11 justify-center" : "w-full px-3"}
              ${active
                ? "bg-brand-50 font-semibold text-brand-700 before:absolute before:inset-y-2 before:-left-3 before:w-1 before:rounded-r-full before:bg-brand-600"
                : "font-medium text-ink-muted hover:bg-surface-subtle hover:text-ink"}`}>
        <Icon aria-hidden="true" className="size-5 shrink-0" />
        <span className={collapsed ? "sr-only" : "truncate"}>{item.label}</span>
      </Link>
    </Tooltip>
  );
}
