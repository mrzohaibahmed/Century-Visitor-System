"use client";

import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { TextField } from "@/components/ui/TextField";
import type { RangeChoice, RangePreset } from "@/lib/api/reports";
import { isoDay } from "@/lib/format";

export const PRESETS: { value: RangePreset; label: string }[] = [
  { value: "today", label: "Today" },
  { value: "yesterday", label: "Yesterday" },
  { value: "this_week", label: "This week" },
  { value: "this_month", label: "This month" },
  { value: "custom", label: "Custom" },
];

/**
 * The reporting period. Presets are sent as they are ("this_week"...) and worked out by the server in
 * the organisation's time zone: the browser never computes days. A custom range is applied with
 * "Apply" (the server checks it too: at most 366 days).
 */
export function DateRangeControl({ value, onChange, disabled = false }: {
  value: RangeChoice; onChange: (next: RangeChoice) => void; disabled?: boolean;
}) {
  const [mode, setMode] = useState<RangePreset>(value.range);
  const [from, setFrom] = useState(value.from ?? isoDay());
  const [to, setTo] = useState(value.to ?? isoDay());
  const invalid = mode === "custom" && (!from || !to || from > to);

  function pick(preset: RangePreset) {
    setMode(preset);
    if (preset !== "custom") onChange({ range: preset });
  }

  return (
    <div className={`flex flex-wrap items-end gap-3 ${disabled ? "pointer-events-none opacity-50" : ""}`}
         aria-disabled={disabled || undefined}>
      <div className="w-full max-w-xl overflow-x-auto">
        <SegmentedControl label="Reporting period" value={mode} options={PRESETS} onChange={pick} />
      </div>
      {mode === "custom" && (
        <form className="flex flex-wrap items-end gap-3"
              onSubmit={(e) => { e.preventDefault(); if (!invalid) onChange({ range: "custom", from, to }); }}>
          <TextField label="From" type="date" value={from} onChange={(e) => setFrom(e.target.value)} className="w-40" />
          <TextField label="To" type="date" value={to} onChange={(e) => setTo(e.target.value)} className="w-40"
                     error={from && to && from > to ? "The start date is after the end date." : undefined} />
          <Button type="submit" variant="secondary" disabled={invalid}>Apply</Button>
        </form>
      )}
    </div>
  );
}
