"use client";

import { createContext, useContext } from "react";

import { GatePicker } from "@/components/session/GatePicker";
import { useSession } from "@/components/session/SessionProvider";
import { SystemStatusIndicator } from "@/components/system/SystemStatusIndicator";
import { type SystemHealth, useSystemHealth } from "@/hooks/useSystemHealth";

import { Sidebar } from "./Sidebar";
import { UserMenu } from "./UserMenu";

const SystemHealthContext = createContext<SystemHealth | null>(null);

/** Shared health state: one poll for the whole shell (top bar + dashboard card). */
export function useSharedSystemHealth(): SystemHealth {
  const value = useContext(SystemHealthContext);
  if (!value) throw new Error("useSharedSystemHealth must be used inside <AppShell>");
  return value;
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const health = useSystemHealth();
  const { user } = useSession();
  return (
    <SystemHealthContext.Provider value={health}>
      <div className="flex min-h-screen">
        <Sidebar role={user.role} />
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex h-16 items-center justify-between gap-4 border-b border-border bg-surface px-6">
            <SystemStatusIndicator state={health.state} />
            <div className="flex items-center gap-4">
              <GatePicker />
              <UserMenu />
            </div>
          </header>
          <main className="flex-1 px-6 py-6">{children}</main>
        </div>
      </div>
    </SystemHealthContext.Provider>
  );
}
