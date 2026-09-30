import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { getServerSession } from "@/lib/api/server";

import { ReportsWorkspace } from "./ReportsWorkspace";

export const metadata: Metadata = { title: "Reports" };

/**
 * Reports: administrators (the admin layout) holding reports:view. Checked on the server before anything
 * renders; the API refuses every report request without the permission anyway (and audits it).
 */
export default async function ReportsPage() {
  const me = await getServerSession();
  if (!me) redirect("/login");
  if (!me.permissions.includes("reports:view")) redirect("/dashboard");
  return <ReportsWorkspace />;
}
