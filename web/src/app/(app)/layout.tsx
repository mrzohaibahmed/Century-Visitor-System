import { redirect } from "next/navigation";

import { AppShell } from "@/components/layout/AppShell";
import { SessionProvider } from "@/components/session/SessionProvider";
import { getServerSession } from "@/lib/api/server";

// Every page in this group needs a valid session, checked on the server before rendering.
export const dynamic = "force-dynamic";

export default async function AppLayout({ children }: LayoutProps<"/">) {
  const me = await getServerSession();
  if (!me) redirect("/login");
  return (
    <SessionProvider initial={me}>
      <AppShell>{children}</AppShell>
    </SessionProvider>
  );
}
