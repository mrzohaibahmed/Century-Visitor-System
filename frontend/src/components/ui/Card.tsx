/**
 * A surface for one group of content. The title is optional (a plain panel); `divided`
 * draws a line under the header, `footer` holds the card's actions, `icon` sits beside the title.
 */
export function Card({ title, description, icon, actions, footer, divided = true, className = "", children }: {
  title?: string;
  description?: string;
  icon?: React.ReactNode;
  actions?: React.ReactNode;
  footer?: React.ReactNode;
  divided?: boolean;
  className?: string;
  children: React.ReactNode;
}) {
  const hasHeader = Boolean(title || actions);
  return (
    <section className={`rounded-2xl border border-border bg-surface shadow-card ${className}`}>
      {hasHeader && (
        <header className={`flex items-start justify-between gap-4 px-6 pt-5 ${divided ? "border-b border-border pb-4" : ""}`}>
          <div className="flex min-w-0 items-start gap-3">
            {icon && (
              <span aria-hidden="true" className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-700 [&_svg]:size-5">
                {icon}
              </span>
            )}
            <div className="min-w-0">
              {title && <h2 className="text-heading text-ink">{title}</h2>}
              {description && <p className="mt-1 text-sm text-ink-muted">{description}</p>}
            </div>
          </div>
          {actions}
        </header>
      )}
      <div className={`px-6 pb-6 ${hasHeader && !divided ? "pt-4" : "pt-5"}`}>{children}</div>
      {footer && <footer className="flex flex-wrap items-center justify-end gap-3 border-t border-border px-6 py-4">{footer}</footer>}
    </section>
  );
}
