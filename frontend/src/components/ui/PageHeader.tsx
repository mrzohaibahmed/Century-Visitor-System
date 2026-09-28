/** The top of a page: the one h1, an optional line of context, and page-level actions. */
export function PageHeader({ title, description, actions }: {
  title: string;
  description?: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-title text-ink">{title}</h1>
        {description && <p className="mt-1.5 max-w-2xl text-base text-ink-muted">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-3">{actions}</div>}
    </div>
  );
}
