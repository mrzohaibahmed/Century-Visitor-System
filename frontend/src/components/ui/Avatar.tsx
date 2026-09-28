/** Initials in a circle, for a person without a photo. Decorative: the name is always shown beside it. */
export function Avatar({ name, size = "md" }: { name: string; size?: "sm" | "md" }) {
  const initials = name.trim().split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]!.toUpperCase()).join("") || "?";
  return (
    <span aria-hidden="true"
          className={`flex shrink-0 items-center justify-center rounded-full bg-brand-50 font-semibold text-brand-700
            ${size === "sm" ? "size-9 text-sm" : "size-12 text-base"}`}>
      {initials}
    </span>
  );
}
