/**
 * A short visual label for an icon-only control, shown on hover and keyboard focus. Decorative
 * (aria-hidden): the control itself must carry the accessible name (aria-label or sr-only text).
 */
export function Tooltip({ label, side = "right", disabled = false, children }: {
  label: string;
  side?: "right" | "bottom";
  disabled?: boolean;
  children: React.ReactNode;
}) {
  if (disabled) return <>{children}</>;
  const position = side === "right"
    ? "left-full top-1/2 ml-2 -translate-y-1/2"
    : "right-0 top-full mt-2";
  return (
    <span className="group/tooltip relative inline-flex">
      {children}
      <span aria-hidden="true"
            className={`pointer-events-none absolute z-50 whitespace-nowrap rounded-lg bg-ink px-2.5 py-1.5 text-xs
              font-medium text-canvas opacity-0 shadow-overlay transition-opacity duration-150
              group-hover/tooltip:opacity-100 group-has-focus-visible/tooltip:opacity-100 ${position}`}>
        {label}
      </span>
    </span>
  );
}
