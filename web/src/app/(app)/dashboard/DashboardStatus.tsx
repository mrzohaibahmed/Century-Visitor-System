"use client";

import { useSharedSystemHealth } from "@/components/layout/AppShell";
import { SystemStatusCard } from "@/components/system/SystemStatusCard";

export function DashboardStatus() {
  return <SystemStatusCard health={useSharedSystemHealth()} />;
}
