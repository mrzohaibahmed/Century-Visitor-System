"use client";

import { useCallback, useState } from "react";

import { DateRangeControl } from "@/components/reports/DateRangeControl";
import { periodText } from "@/components/reports/ReportParts";
import { ReportTabs, type Tab, TabPanel } from "@/components/reports/ReportTabs";
import { PageHeader } from "@/components/ui/PageHeader";
import type { RangeChoice, ReportRange } from "@/lib/api/reports";

import { DenialsReport } from "./DenialsReport";
import { useFilterOptions } from "./filterOptions";
import { GuardsReport, HostsDepartmentsReport } from "./GroupReports";
import { InsideReport } from "./InsideReport";
import { OverviewReport } from "./OverviewReport";
import { VisitorsReport } from "./VisitorsReport";
import { VisitsReport } from "./VisitsReport";

type TabId = "overview" | "visits" | "visitors" | "hosts" | "guards" | "inside" | "security";

const TABS: Tab<TabId>[] = [
  { id: "overview", label: "Overview" },
  { id: "visits", label: "Visits" },
  { id: "visitors", label: "Visitors" },
  { id: "hosts", label: "Hosts & departments" },
  { id: "guards", label: "Guards" },
  { id: "inside", label: "Currently inside" },
  { id: "security", label: "Security" },
];
const WITH_FILTER_OPTIONS = new Set<TabId>(["visits", "visitors", "hosts", "inside", "security"]);

/**
 * The Reports workspace. Only the open tab is mounted, so only its report is requested; every figure
 * comes from the server for the chosen period (Asia/Karachi days, worked out by the server).
 */
export function ReportsWorkspace() {
  const [tab, setTab] = useState<TabId>("overview");
  const [range, setRange] = useState<RangeChoice>({ range: "today" });
  const [period, setPeriod] = useState<ReportRange | null>(null);
  const [needOptions, setNeedOptions] = useState(false);
  const options = useFilterOptions(needOptions);
  const onPeriod = useCallback((r: ReportRange | null) => setPeriod(r), []);

  function selectTab(id: TabId) {
    setTab(id);
    setPeriod(null);
    if (WITH_FILTER_OPTIONS.has(id)) setNeedOptions(true);
  }

  const common = { range, onPeriod, options };
  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <PageHeader title="Reports"
                  description="Visits, visitors, hosts, operators and refused entries. Every figure is calculated by the server; ID numbers and phone numbers are always masked." />

      <section aria-label="Reporting period" className="space-y-3 rounded-2xl border border-border bg-surface p-4 shadow-card">
        <DateRangeControl value={range} onChange={setRange} disabled={tab === "inside"} />
        <p className="text-sm text-ink-muted" aria-live="polite" data-testid="active-period">
          {tab === "inside"
            ? "Currently inside shows who is on site right now: the reporting period does not apply."
            : period ? <>Reporting period: <span className="font-medium text-ink">{periodText(period)}</span></> : "Loading…"}
        </p>
      </section>

      <ReportTabs label="Reports" tabs={TABS} value={tab} onChange={selectTab} />
      <TabPanel id={tab}>
        {tab === "overview" && <OverviewReport range={range} onPeriod={onPeriod} />}
        {tab === "visits" && <VisitsReport {...common} />}
        {tab === "visitors" && <VisitorsReport {...common} />}
        {tab === "hosts" && <HostsDepartmentsReport {...common} />}
        {tab === "guards" && <GuardsReport range={range} onPeriod={onPeriod} />}
        {tab === "inside" && <InsideReport options={options} />}
        {tab === "security" && <DenialsReport {...common} />}
      </TabPanel>
    </div>
  );
}
