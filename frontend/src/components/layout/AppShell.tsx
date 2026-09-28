"use client";

import { Menu, PanelLeftClose, PanelLeftOpen, X } from "lucide-react";
import { usePathname } from "next/navigation";
import { createContext, useContext, useEffect, useRef, useState } from "react";

import { NotificationBell } from "@/components/notifications/NotificationBell";
import { GatePicker } from "@/components/session/GatePicker";
import { useSession } from "@/components/session/SessionProvider";
import { SystemStatusIndicator } from "@/components/system/SystemStatusIndicator";
import { type SystemHealth, useSystemHealth } from "@/hooks/useSystemHealth";
import type { Role } from "@/lib/api/auth";
import { sectionTitle } from "@/lib/navigation";
import { applyTheme, rememberSidebar, type Theme } from "@/lib/theme";

import { Brand, SidebarNav } from "./Sidebar";
import { UserMenu } from "./UserMenu";

const SystemHealthContext = createContext<SystemHealth | null>(null);

/** Shared health state: one poll for the whole shell (top bar + dashboard card). */
export function useSharedSystemHealth(): SystemHealth {
  const value = useContext(SystemHealthContext);
  if (!value) throw new Error("useSharedSystemHealth must be used inside <AppShell>");
  return value;
}

/**
 * The frame around every signed-in page: a sidebar (persistent from lg, collapsible to icons;
 * a drawer below lg) and a top bar with the section, gate, system status and notifications.
 */
export function AppShell({ initialCollapsed = false, initialTheme = "dark", children }: {
  initialCollapsed?: boolean;
  initialTheme?: Theme;
  children: React.ReactNode;
}) {
  const health = useSystemHealth();
  const { user } = useSession();
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(initialCollapsed);
  const [theme, setTheme] = useState<Theme>(initialTheme);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const menuButton = useRef<HTMLButtonElement>(null);

  function changeTheme(next: Theme) {
    setTheme(next);
    applyTheme(next);
  }

  function toggleSidebar() {
    rememberSidebar(!collapsed);
    setCollapsed(!collapsed);
  }

  function closeDrawer() {
    setDrawerOpen(false);
    menuButton.current?.focus();
  }

  return (
    <SystemHealthContext.Provider value={health}>
      <div className="flex min-h-screen">
        <aside className={`sticky top-0 hidden h-screen shrink-0 flex-col border-r border-border bg-surface
          transition-[width] duration-200 lg:flex ${collapsed ? "w-[4.75rem]" : "w-64"}`}>
          <div className={`flex h-16 shrink-0 items-center border-b border-border ${collapsed ? "justify-center" : "px-4"}`}>
            <Brand collapsed={collapsed} />
          </div>
          {/* Collapsed: no scroll container, so the tooltips beside the icons are not clipped. */}
          <div className={collapsed ? "flex-1" : "flex-1 overflow-y-auto"}>
            <SidebarNav role={user.role} collapsed={collapsed} />
          </div>
          <UserMenu collapsed={collapsed} theme={theme} onTheme={changeTheme} />
        </aside>

        <NavigationDrawer open={drawerOpen} onClose={closeDrawer} role={user.role} theme={theme} onTheme={changeTheme}
                          pathname={pathname} />

        <div className="flex min-w-0 flex-1 flex-col">
          <header className="sticky top-0 z-30 flex h-16 items-center gap-2 border-b border-border bg-canvas/90 px-4
            backdrop-blur-sm sm:gap-3 sm:px-6 lg:px-8">
            <button ref={menuButton} type="button" onClick={() => setDrawerOpen(true)} aria-label="Open navigation"
                    aria-expanded={drawerOpen}
                    className="-ml-1.5 inline-flex size-11 shrink-0 items-center justify-center rounded-xl text-ink-muted
                      transition-colors hover:bg-surface-subtle hover:text-ink lg:hidden">
              <Menu aria-hidden="true" className="size-6" />
            </button>
            <button type="button" onClick={toggleSidebar} aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
                    aria-expanded={!collapsed} title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
                    className="-ml-1.5 hidden size-11 shrink-0 items-center justify-center rounded-xl text-ink-muted
                      transition-colors hover:bg-surface-subtle hover:text-ink lg:inline-flex">
              {collapsed
                ? <PanelLeftOpen aria-hidden="true" className="size-5" />
                : <PanelLeftClose aria-hidden="true" className="size-5" />}
            </button>
            <p className="min-w-0 flex-1 truncate text-base font-semibold text-ink">{sectionTitle(pathname)}</p>
            <div className="flex shrink-0 items-center gap-1.5 sm:gap-2">
              <GatePicker />
              <SystemStatusIndicator state={health.state} />
              <NotificationBell />
            </div>
          </header>
          <main className="flex-1 px-4 py-6 sm:px-6 lg:px-8 lg:py-8">{children}</main>
        </div>
      </div>
    </SystemHealthContext.Provider>
  );
}

/** Below lg: the navigation in a modal drawer (native <dialog>: focus trap, Escape, inert page). */
function NavigationDrawer({ open, onClose, role, theme, onTheme, pathname }: {
  open: boolean;
  onClose: () => void;
  role: Role;
  theme: Theme;
  onTheme: (theme: Theme) => void;
  pathname: string;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const openedAt = useRef(pathname);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) { openedAt.current = pathname; dialog.showModal?.(); }
    if (!open && dialog.open) dialog.close?.();
  }, [open, pathname]);

  useEffect(() => {
    // Navigating (a link, or the browser's back button) closes the drawer.
    if (open && pathname !== openedAt.current) onClose();
  }, [open, pathname, onClose]);

  return (
    <dialog ref={ref} aria-label="Navigation"
            onCancel={(event) => { event.preventDefault(); onClose(); }}
            onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}
            className="fixed inset-y-0 left-0 m-0 h-dvh max-h-dvh w-72 max-w-[85vw] border-r border-border bg-surface p-0
              text-ink shadow-overlay backdrop:bg-overlay open:animate-drawer-in lg:hidden">
      {open && (
        <div className="flex h-full flex-col">
          <div className="flex h-16 shrink-0 items-center justify-between gap-2 border-b border-border pr-2 pl-4">
            <Brand />
            <button type="button" onClick={onClose} aria-label="Close navigation"
                    className="inline-flex size-11 items-center justify-center rounded-xl text-ink-muted transition-colors
                      hover:bg-surface-subtle hover:text-ink">
              <X aria-hidden="true" className="size-5" />
            </button>
          </div>
          <div className="flex-1 overflow-y-auto">
            <SidebarNav role={role} />
          </div>
          <UserMenu theme={theme} onTheme={onTheme} />
        </div>
      )}
    </dialog>
  );
}
