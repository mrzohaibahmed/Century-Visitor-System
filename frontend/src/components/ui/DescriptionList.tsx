/**
 * Label/value pairs (a <dl>): label above value on phones, side by side from sm up.
 * `caps`: the value is human-readable visitor data, shown in capitals (see `caps` in globals.css).
 */
export function DescriptionList({ items }: { items: { label: string; value: React.ReactNode; caps?: boolean }[] }) {
  return (
    <dl className="divide-y divide-border">
      {items.map(({ label, value, caps }) => (
        <div key={label} className="grid gap-1 py-3 first:pt-0 last:pb-0 sm:grid-cols-[10rem_1fr] sm:gap-4">
          <dt className="text-sm text-ink-muted">{label}</dt>
          <dd className={`min-w-0 text-base font-medium break-words text-ink${caps ? " caps" : ""}`}>{value}</dd>
        </div>
      ))}
    </dl>
  );
}
