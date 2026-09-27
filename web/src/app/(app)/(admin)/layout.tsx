import { redirect } from "next/navigation";

import { getServerSession } from "@/lib/api/server";

/**
 * Admin-only pages. Hiding them from guards is UX; the API independently
 * refuses every admin request from a guard (and audits the attempt).
 */
export default async function AdminLayout({ children }: LayoutProps<"/">) {
  const me = await getServerSession();
  if (!me) redirect("/login");
  if (me.user.role !== "ADMIN") redirect("/dashboard");
  return children;
}
