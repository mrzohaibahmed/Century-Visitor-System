"use client";

import { ChevronsUpDown, KeyRound, Power } from "lucide-react";
import Link from "next/link";
import { useEffect, useId, useRef, useState } from "react";

import { CHANGE_PASSWORD_PATH, useSession } from "@/components/session/SessionProvider";
import { Avatar } from "@/components/ui/Avatar";
import { Button } from "@/components/ui/Button";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { Tooltip } from "@/components/ui/Tooltip";
import type { Theme } from "@/lib/theme";

const ROLE_LABELS = { ADMIN: "Administrator", GUARD: "Guard" } as const;

/**
 * The signed-in user at the foot of the sidebar: an account menu (change password, theme) and an
 * always-visible Log out.
 */
export function UserMenu({ collapsed = false, theme, onTheme }: {
  collapsed?: boolean;
  theme: Theme;
  onTheme: (theme: Theme) => void;
}) {
  const { user, signOut } = useSession();
  const [open, setOpen] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const wrapper = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const panelId = useId();
  const name = user.display_name || user.username;

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: MouseEvent) => {
      if (!wrapper.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") { setOpen(false); trigger.current?.focus(); }
    };
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onPointer); document.removeEventListener("keydown", onKey); };
  }, [open]);

  return (
    <div className={`border-t border-border ${collapsed ? "flex flex-col items-center gap-1 p-2" : "space-y-1 p-3"}`}>
      <div ref={wrapper} className="relative">
        <Tooltip label={name} disabled={!collapsed}>
          <button ref={trigger} type="button" onClick={() => setOpen(!open)} aria-expanded={open} aria-controls={panelId}
                  className={`flex min-h-12 items-center gap-3 rounded-xl text-left transition-colors hover:bg-surface-subtle
                    ${collapsed ? "w-11 justify-center" : "w-full px-2 py-1.5"}`}>
            <Avatar name={name} size="sm" />
            <span className={collapsed ? "sr-only" : "min-w-0 flex-1"}>
              <span className="block truncate text-sm font-semibold text-ink">{name}</span>
              <span className="block truncate text-xs text-ink-muted">{ROLE_LABELS[user.role]}</span>
            </span>
            <span className="sr-only">, account menu</span>
            {!collapsed && <ChevronsUpDown aria-hidden="true" className="size-4 shrink-0 text-ink-subtle" />}
          </button>
        </Tooltip>

        {open && (
          <div id={panelId} className="absolute bottom-full left-0 z-40 mb-2 w-64 space-y-3 rounded-xl border border-border
            bg-surface-elevated p-2 shadow-overlay">
            <Link href={CHANGE_PASSWORD_PATH} onClick={() => setOpen(false)}
                  className="flex min-h-11 items-center gap-3 rounded-lg px-3 text-sm font-medium text-ink transition-colors
                    hover:bg-surface-subtle">
              <KeyRound aria-hidden="true" className="size-4 text-ink-muted" />
              Change password
            </Link>
            <div className="border-t border-border px-1 pt-3 pb-1">
              <SegmentedControl label="Theme" value={theme} onChange={onTheme}
                                options={[{ value: "dark", label: "Dark" }, { value: "light", label: "Light" }]} />
            </div>
          </div>
        )}
      </div>

      <Tooltip label="Log out" disabled={!collapsed}>
        <Button variant="ghost" loading={signingOut} aria-label={collapsed ? "Log out" : undefined}
                className={collapsed ? "w-11 px-0" : "w-full justify-start px-3"}
                onClick={() => { setSigningOut(true); void signOut(); }}>
          {!signingOut && <Power aria-hidden="true" />}
          {!collapsed && "Log out"}
        </Button>
      </Tooltip>
    </div>
  );
}
