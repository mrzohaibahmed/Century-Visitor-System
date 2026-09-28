import { LoaderCircle } from "lucide-react";
import Link from "next/link";

type Variant = "primary" | "secondary" | "danger" | "ghost";
type Size = "sm" | "md" | "lg";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-brand-600 text-white shadow-card hover:bg-brand-hover disabled:bg-brand-600/60 disabled:shadow-none",
  secondary: "border border-border-strong bg-surface text-ink shadow-card hover:bg-surface-subtle disabled:text-ink-muted disabled:shadow-none",
  danger: "bg-danger-solid text-white shadow-card hover:bg-danger-solid/90 disabled:bg-danger-solid/60 disabled:shadow-none",
  ghost: "text-ink-muted hover:bg-canvas hover:text-ink disabled:text-ink-muted/60",
};

/** md matches the text inputs (44 px); lg is for touch-first gate flows (check-in, check-out). */
const SIZES: Record<Size, string> = {
  sm: "min-h-9 px-3 text-sm [&_svg]:size-4",
  md: "min-h-11 px-4 text-sm [&_svg]:size-4",
  lg: "min-h-14 px-6 text-base [&_svg]:size-5",
};

export function buttonClasses({ variant = "primary", size = "md", className = "" }:
  { variant?: Variant; size?: Size; className?: string } = {}): string {
  return `inline-flex items-center justify-center gap-2 rounded-xl py-2 font-semibold transition-colors duration-150
    disabled:cursor-not-allowed [&_svg]:shrink-0 ${VARIANTS[variant]} ${SIZES[size]} ${className}`;
}

export function Button({ variant = "primary", size = "md", loading = false, className = "", children, disabled, ...props }:
  React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: Size; loading?: boolean }) {
  return (
    <button
      {...props}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={buttonClasses({ variant, size, className })}
    >
      {loading && <LoaderCircle aria-hidden="true" className="animate-spin" />}
      {children}
    </button>
  );
}

/** A link that looks like a button (navigation, not an action). */
export function ButtonLink({ variant = "primary", size = "md", className = "", ...props }:
  React.ComponentProps<typeof Link> & { variant?: Variant; size?: Size }) {
  return <Link {...props} className={buttonClasses({ variant, size, className })} />;
}
