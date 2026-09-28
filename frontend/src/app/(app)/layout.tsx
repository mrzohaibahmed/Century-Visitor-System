import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { AppShell } from "@/components/layout/AppShell";
import { SessionProvider } from "@/components/session/SessionProvider";
import { getServerSession } from "@/lib/api/server";
import { SIDEBAR_COOKIE, THEME_COOKIE, themeFrom } from "@/lib/theme";

// Every page in this group needs a valid session, checked on the server before rendering.
export const dynamic = "force-dynamic";

export default async function AppLayout({ children }: LayoutProps<"/">) {
  const me = await getServerSession();
  if (!me) redirect("/login");
  const jar = await cookies();
  return (
    <SessionProvider initial={me}>
      <AppShell initialCollapsed={jar.get(SIDEBAR_COOKIE)?.value === "collapsed"}
                initialTheme={themeFrom(jar.get(THEME_COOKIE)?.value)}>
        {children}
      </AppShell>
    </SessionProvider>
  );
}
