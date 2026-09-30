"use client";

import { useRef } from "react";

export type Tab<T extends string> = { id: T; label: string };

/** Tabs (WAI-ARIA pattern): arrow keys, Home and End move between them; only the chosen panel is shown. */
export function ReportTabs<T extends string>({ tabs, value, onChange, label }: {
  tabs: Tab<T>[]; value: T; onChange: (id: T) => void; label: string;
}) {
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});

  function onKeyDown(event: React.KeyboardEvent, index: number) {
    const last = tabs.length - 1;
    const next = { ArrowRight: index === last ? 0 : index + 1, ArrowLeft: index === 0 ? last : index - 1,
                   Home: 0, End: last }[event.key];
    if (next === undefined) return;
    event.preventDefault();
    onChange(tabs[next].id);
    refs.current[tabs[next].id]?.focus();
  }

  return (
    <div role="tablist" aria-label={label} className="flex gap-1 overflow-x-auto border-b border-border">
      {tabs.map((tab, i) => {
        const selected = tab.id === value;
        return (
          <button key={tab.id} ref={(el) => { refs.current[tab.id] = el; }} type="button" role="tab"
                  id={`tab-${tab.id}`} aria-selected={selected} aria-controls={`panel-${tab.id}`}
                  tabIndex={selected ? 0 : -1} onClick={() => onChange(tab.id)} onKeyDown={(e) => onKeyDown(e, i)}
                  className={`-mb-px min-h-11 shrink-0 border-b-2 px-4 text-sm font-medium whitespace-nowrap transition-colors
                    ${selected ? "border-brand-600 text-brand-700" : "border-transparent text-ink-muted hover:text-ink"}`}>
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}

export function TabPanel({ id, children }: { id: string; children: React.ReactNode }) {
  return (
    <div role="tabpanel" id={`panel-${id}`} aria-labelledby={`tab-${id}`} tabIndex={0} className="space-y-4 outline-none">
      {children}
    </div>
  );
}
