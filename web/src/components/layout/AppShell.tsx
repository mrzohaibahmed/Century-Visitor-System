"use client";

import { createContext, useContext } from "react";

import { SystemStatusIndicator } from "@/components/system/SystemStatusIndicator";
import { type SystemHealth, useSystemHealth } from "@/hooks/useSystemHealth";

import { Sidebar } from "./Sidebar";

const SystemHealthContext = createContext<SystemHealth | null>(null);

/** Shared health state: one poll for the whole shell (top bar + dashboard card). */
export function useSharedSystemHealth(): SystemHealth {
  const value = useContext(SystemHealthContext);
  if (!value) throw new Error("useSharedSystemHealth must be used inside <AppShell>");
  return value;
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const health = useSystemHealth();
  return (
    <SystemHealthContext.Provider value={health}>
      <div className="flex min-h-screen">
        <Sidebar />
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex h-14 items-center justify-between border-b border-border bg-surface px-6">
            <span className="text-sm font-medium text-ink-muted">Gate workstation</span>
            <SystemStatusIndicator state={health.state} />
          </header>
          <main className="flex-1 px-6 py-6">{children}</main>
        </div>
      </div>
    </SystemHealthContext.Provider>
  );
}
