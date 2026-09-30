"use client";

import { LogIn, LogOut, ShieldAlert, ShieldX, Timer, Users, UsersRound } from "lucide-react";
import { useEffect } from "react";

import { BarList, ColumnChart, type Point } from "@/components/reports/charts";
import { formatDay, ReportError } from "@/components/reports/ReportParts";
import { useReport } from "@/components/reports/useReport";
import { Card } from "@/components/ui/Card";
import { Skeleton } from "@/components/ui/Skeleton";
import { StatTile } from "@/components/ui/StatTile";
import { getOverview, type Overview, type RangeChoice, type ReportRange } from "@/lib/api/reports";
import { formatMinutes } from "@/lib/format";

const STATUS_LABELS: Record<string, string> = { CHECKED_IN: "Inside", CHECKED_OUT: "Checked out" };
const hourLabel = (h: number) => `${String(h).padStart(2, "0")}:00`;

/** Chart points from the server's series. Bucket starts come with the organisation's offset
 * ("2026-09-30T14:00:00+05:00"): the labels are read from the text, never converted in the browser. */
function timePoints(series: Overview["series"]): Point[] {
  return series.over_time.map((p) => {
    const day = p.start.slice(0, 10);
    const hour = p.start.slice(11, 16);
    return series.bucket === "hour"
      ? { key: p.start, axis: hour.slice(0, 2), label: `${formatDay(day)} ${hour}`, value: p.count }
      : { key: p.start, axis: formatDay(day, false), label: formatDay(day), value: p.count };
  });
}

function ChartSkeleton() {
  return <div role="status"><span className="sr-only">Loading chart…</span><Skeleton className="h-48 w-full" /></div>;
}

function NoVisits() {
  return <p className="py-10 text-center text-sm text-ink-muted">No visits in this reporting period.</p>;
}

export function OverviewReport({ range, onPeriod }: { range: RangeChoice; onPeriod: (r: ReportRange | null) => void }) {
  const overview = useReport(JSON.stringify(range), (signal) => getOverview(range, { signal }));
  const data = overview.data;
  useEffect(() => onPeriod(data?.range ?? null), [data, onPeriod]);

  if (overview.error) return <ReportError error={overview.error} onRetry={overview.reload} />;

  const t = data?.totals;
  const value = (n: number | undefined) => (n === undefined ? null : n.toLocaleString());
  const empty = data !== null && data.totals.visits === 0;
  const points = data ? timePoints(data.series) : [];

  return (
    <div className={`space-y-6 transition-opacity ${overview.loading && data ? "opacity-70" : ""}`} aria-busy={overview.loading || undefined}>
      <div role="region" aria-label="Totals for the reporting period" className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <StatTile label="Total visits" icon={<LogIn />} tone="brand" value={value(t?.visits)} testId="total-visits" />
          <StatTile label="Unique visitors" icon={<Users />} value={value(t?.unique_visitors)} testId="unique-visitors" />
          <StatTile label="Currently inside" icon={<UsersRound />} value={value(t?.inside_now)} testId="inside-now"
                    hint="Right now, whatever the period." />
          <StatTile label="Checked out" icon={<LogOut />} value={value(t?.checked_out)} testId="checked-out"
                    hint="Visits of this period that have left." />
        </div>
        <div className="grid gap-4 sm:grid-cols-3">
          <StatTile label="Average visit" icon={<Timer />} testId="avg-duration"
                    value={t ? formatMinutes(t.avg_duration_minutes) : null} hint="Completed visits only." />
          <StatTile label="Denied entries" icon={<ShieldX />} tone="warn" value={value(t?.denied_entries)} testId="denied"
                    hint="All entries refused at the gate." />
          <StatTile label="Watchlist matches" icon={<ShieldAlert />} tone="warn" value={value(t?.watchlist_matches)}
                    testId="watchlist" hint="Refusals because of the watchlist (a separate count)." />
        </div>
      </div>

      <div className="grid gap-6 xl:grid-cols-2">
        <Card title="Visits over time" description={data?.series.bucket === "hour" ? "Per hour" : "Per day"} className="min-w-0">
          {!data ? <ChartSkeleton /> : empty ? <NoVisits /> : (
            <ColumnChart title="Visits over time" points={points}
                         labelEvery={data.series.bucket === "hour" ? 3 : Math.max(1, Math.ceil(points.length / 10))} />
          )}
        </Card>
        <Card title="Peak hours" description="Check-ins by hour of the day" className="min-w-0">
          {!data ? <ChartSkeleton /> : empty ? <NoVisits /> : (
            <ColumnChart title="Peak hours" labelEvery={3}
                         points={data.series.peak_hours.map((h) => ({
                           key: String(h.hour), axis: String(h.hour).padStart(2, "0"),
                           label: `${hourLabel(h.hour)}–${hourLabel((h.hour + 1) % 24)}`, value: h.count,
                         }))} />
          )}
        </Card>
        <Card title="Visits by department" className="min-w-0">
          {!data ? <ChartSkeleton /> : empty ? <NoVisits /> : (
            <BarList title="Visits by department"
                     items={data.series.by_department.map((d) => ({ key: d.id ?? "none", label: d.name ?? "No department", value: d.count }))} />
          )}
        </Card>
        <Card title="Visits by status" description="Visits of this period, as they stand now" className="min-w-0">
          {!data ? <ChartSkeleton /> : empty ? <NoVisits /> : (
            <BarList title="Visits by status"
                     items={data.series.by_status.map((s) => ({ key: s.status, label: STATUS_LABELS[s.status] ?? s.status, value: s.count }))} />
          )}
        </Card>
      </div>
    </div>
  );
}
