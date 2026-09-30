"use client";

import { useEffect, useRef, useState } from "react";

/**
 * In-house SVG charts for the reports (no chart library). One series each, so one colour (the brand
 * blue, checked against both theme surfaces) and no legend: the card's title names what is plotted.
 * Bars at most 24 px wide with a 4 px rounded end on a single baseline; hairline gridlines; text in the
 * text colours, never the bar colour. The hover tooltip only repeats what the table view shows, so
 * nothing depends on a pointer; screen readers get a written summary and the table.
 */

export type Point = { key: string; axis: string; label: string; value: number };

const PLOT_H = 160;
const AXIS_W = 36;
const AXIS_H = 22;
const TOP = 8;

function niceMax(max: number): number {
  if (max <= 4) return Math.max(max, 1);
  const step = 10 ** Math.floor(Math.log10(max));
  return Math.ceil(max / step) * step;
}

function useWidth(fallback = 640) {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(fallback);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(240, Math.floor(entry.contentRect.width))));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return { ref, width };
}

/** A column with a 4 px rounded top and a square base. */
function columnPath(x: number, y: number, w: number, h: number): string {
  const r = Math.min(4, w / 2, h);
  const base = y + h;
  return `M${x},${base} V${y + r} Q${x},${y} ${x + r},${y} H${x + w - r} Q${x + w},${y} ${x + w},${y + r} V${base} Z`;
}

export function ColumnChart({ title, points, unit = "visits", labelEvery = 1 }: {
  title: string; points: Point[]; unit?: string; labelEvery?: number;
}) {
  const { ref, width } = useWidth();
  const [active, setActive] = useState<number | null>(null);
  const total = points.reduce((sum, p) => sum + p.value, 0);
  const peak = points.reduce<Point | null>((best, p) => (!best || p.value > best.value ? p : best), null);
  const max = niceMax(peak?.value ?? 0);
  const plotW = width - AXIS_W;
  const slot = points.length ? plotW / points.length : plotW;
  const bar = Math.max(2, Math.min(24, slot - 2));
  const y = (v: number) => TOP + PLOT_H - (v / max) * PLOT_H;
  const summary = total
    ? `${title}: ${total.toLocaleString()} ${unit} in total; the most, ${peak!.value.toLocaleString()}, at ${peak!.label}.`
    : `${title}: no ${unit} in this period.`;

  return (
    <figure className="space-y-3">
      <div ref={ref} className="relative">
        <svg width={width} height={TOP + PLOT_H + AXIS_H} role="img" aria-label={summary} className="block overflow-visible">
          {[0, max / 2, max].map((tick) => (
            <g key={tick}>
              <line x1={AXIS_W} x2={width} y1={y(tick)} y2={y(tick)} className="stroke-border" strokeWidth={1} />
              <text x={AXIS_W - 6} y={y(tick)} dy="0.32em" textAnchor="end" className="fill-ink-muted text-[11px] tabular-nums">
                {Number.isInteger(tick) ? tick.toLocaleString() : ""}
              </text>
            </g>
          ))}
          {points.map((p, i) => {
            const x = AXIS_W + i * slot + (slot - bar) / 2;
            const h = (p.value / max) * PLOT_H;
            return (
              <g key={p.key}>
                {p.value > 0 && (
                  <path d={columnPath(x, y(p.value), bar, h)}
                        className={`fill-brand-600 transition-opacity ${active !== null && active !== i ? "opacity-60" : ""}`} />
                )}
                {i % labelEvery === 0 && (
                  <text x={AXIS_W + i * slot + slot / 2} y={TOP + PLOT_H + 15} textAnchor="middle"
                        className="fill-ink-muted text-[11px]">{p.axis}</text>
                )}
                {/* The hit area: the whole slot, bigger than the bar. */}
                <rect x={AXIS_W + i * slot} y={TOP} width={slot} height={PLOT_H} fill="transparent" aria-hidden="true"
                      onPointerEnter={() => setActive(i)} onPointerLeave={() => setActive(null)} />
              </g>
            );
          })}
        </svg>
        {active !== null && points[active] && (
          <div role="presentation"
               className="pointer-events-none absolute top-0 -translate-x-1/2 rounded-lg border border-border bg-surface-elevated px-3 py-2 text-xs whitespace-nowrap shadow-overlay"
               style={{ left: Math.min(Math.max(AXIS_W + active * slot + slot / 2, 60), width - 60) }}>
            <p className="font-semibold text-ink tabular-nums">{points[active].value.toLocaleString()} {unit}</p>
            <p className="text-ink-muted">{points[active].label}</p>
          </div>
        )}
      </div>
      <DataView title={title} rows={points.map((p) => [p.label, p.value])} valueHeader={unit} />
    </figure>
  );
}

/** Horizontal bars with the value at each bar's end: for categories (departments, statuses). */
export function BarList({ title, items, unit = "visits" }: {
  title: string; items: { key: string; label: string; value: number }[]; unit?: string;
}) {
  const max = Math.max(1, ...items.map((i) => i.value));
  return (
    <ul aria-label={title} className="space-y-2.5">
      {items.map((item) => (
        <li key={item.key} className="grid grid-cols-[minmax(0,10rem)_1fr_auto] items-center gap-3 text-sm">
          <span className="caps truncate text-ink" title={item.label}>{item.label}</span>
          <svg width="100%" height="12" aria-hidden="true" className="block">
            {item.value > 0 && <rect x="0" y="0" width={`${(item.value / max) * 100}%`} height="12" rx="4" className="fill-brand-600" />}
          </svg>
          <span className="text-right font-medium text-ink tabular-nums">
            {item.value.toLocaleString()}<span className="sr-only"> {unit}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

/** The chart's data as a table (collapsed by default): the accessible view and the tooltip's backup. */
function DataView({ title, rows, valueHeader }: { title: string; rows: [string, number][]; valueHeader: string }) {
  return (
    <details className="text-sm">
      <summary className="cursor-pointer text-ink-muted hover:text-ink">Show as table</summary>
      <div className="mt-2 max-h-64 overflow-y-auto rounded-xl border border-border">
        <table className="w-full text-left">
          <caption className="sr-only">{title}</caption>
          <thead className="text-xs text-ink-muted uppercase">
            <tr><th scope="col" className="px-3 py-2 font-medium">Period</th>
              <th scope="col" className="px-3 py-2 text-right font-medium capitalize">{valueHeader}</th></tr>
          </thead>
          <tbody className="divide-y divide-border">
            {rows.map(([label, value]) => (
              <tr key={label}><td className="px-3 py-1.5 text-ink">{label}</td>
                <td className="px-3 py-1.5 text-right text-ink tabular-nums">{value.toLocaleString()}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}
