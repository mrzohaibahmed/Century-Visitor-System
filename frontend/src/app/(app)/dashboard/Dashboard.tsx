"use client";

import { Clock, LogIn, LogOut, Users } from "lucide-react";
import { useState } from "react";

import { useSession } from "@/components/session/SessionProvider";
import { ButtonLink } from "@/components/ui/Button";
import { StatTile } from "@/components/ui/StatTile";

import { DashboardStatus } from "./DashboardStatus";
import { LongStayAlerts } from "./LongStayAlerts";
import { isLongStay, LONG_STAY_HOURS, TODAY_CAP, useDashboardData } from "./useDashboardData";
import { VisitorActivity } from "./VisitorActivity";

function greeting(hour: number): string {
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}

/** The guard's view of today: who is here, who came and went, and anything that needs attention. */
export function Dashboard() {
  const { user } = useSession();
  const [openedAt] = useState(() => new Date());
  const { inside, today, loadedAt, refreshing, reload } = useDashboardData();
  const now = loadedAt ?? openedAt.getTime();
  const firstName = (user.display_name || user.username).trim().split(/\s+/)[0];

  // null while loading; "—" when a value could not be loaded at all.
  const unknown = (error: string | null) => (error ? "—" : null);
  const longStays = inside.data ? inside.data.items.filter((v) => isLongStay(v, now)) : null;
  const plus = today.data?.capped ? "+" : "";
  const checkedIn = today.data ? `${Math.min(today.data.items.length, TODAY_CAP)}${plus}` : unknown(today.error);
  const checkedOut = today.data
    ? `${today.data.items.filter((v) => v.status === "CHECKED_OUT").length}${plus}` : unknown(today.error);

  return (
    <div className="mx-auto max-w-6xl space-y-8">
      <div className="flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          <p className="text-sm font-medium text-ink-muted" suppressHydrationWarning>
            Today · {openedAt.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" })}
          </p>
          <h1 className="mt-1 text-title text-ink" suppressHydrationWarning>
            {greeting(openedAt.getHours())}, {firstName}
          </h1>
        </div>
        <div className="grid grid-cols-2 gap-3 sm:flex">
          <ButtonLink href="/check-in" size="lg" className="px-4 sm:px-6">
            <LogIn aria-hidden="true" />
            <span className="sm:hidden">Check in</span>
            <span className="hidden sm:inline">Check in visitor</span>
          </ButtonLink>
          <ButtonLink href="/check-out" variant="secondary" size="lg" className="px-4 sm:px-6">
            <LogOut aria-hidden="true" />
            Check out
          </ButtonLink>
        </div>
      </div>

      <section aria-label="Today at a glance" className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
        <StatTile label="On site now" icon={<Users />} tone="brand" testId="inside-count"
                  value={inside.data ? inside.data.total : unknown(inside.error)} hint="All gates" />
        <StatTile label="Checked in" icon={<LogIn />} tone="ok" value={checkedIn} hint="Today, all gates" />
        <StatTile label="Checked out" icon={<LogOut />} value={checkedOut} hint="Of today's check-ins" />
        <StatTile label={`Stays over ${LONG_STAY_HOURS} h`} icon={<Clock />}
                  tone={longStays && longStays.length > 0 ? "warn" : "neutral"}
                  value={longStays ? longStays.length : unknown(inside.error)} hint="Still inside" />
      </section>

      <VisitorActivity today={today} now={now} loadedAt={loadedAt} refreshing={refreshing} onRefresh={() => void reload()} />

      {/* grid-cols-1 (minmax(0, 1fr)): a column never grows past the screen to fit a long row. */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2 lg:items-start">
        <LongStayAlerts longStays={longStays} error={inside.error} now={now} />
        <DashboardStatus />
      </div>
    </div>
  );
}
