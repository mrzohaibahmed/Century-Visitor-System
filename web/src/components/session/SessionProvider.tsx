"use client";

import { usePathname, useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { useIdleLogout } from "@/hooks/useIdleLogout";
import { getMe, logout, type Me, type User } from "@/lib/api/auth";
import { setSessionExpiredHandler } from "@/lib/api/client";

export const CHANGE_PASSWORD_PATH = "/account/password";

type SessionValue = {
  me: Me;
  user: User;
  hasPermission: (permission: string) => boolean;
  refresh: () => Promise<void>;
  signOut: (reason?: "logged_out" | "idle") => Promise<void>;
};

const SessionContext = createContext<SessionValue | null>(null);

export function useSession(): SessionValue {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession must be used inside <SessionProvider>");
  return value;
}

function goToLogin(reason: string) {
  const next = encodeURIComponent(window.location.pathname + window.location.search);
  // Full navigation on purpose: drops all client state from the ended session.
  // eslint-disable-next-line @next/next/no-location-assign-relative-destination
  window.location.assign(`/login?reason=${reason}&next=${next}`);
}

/**
 * Holds the signed-in user (verified on the server by the (app) layout) and
 * reacts to the session ending: server 401s, idle timeout, logout.
 */
export function SessionProvider({ initial, children }: { initial: Me; children: React.ReactNode }) {
  const [me, setMe] = useState(initial);
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    setSessionExpiredHandler(() => goToLogin("expired"));
    return () => setSessionExpiredHandler(null);
  }, []);

  // A new or reset account may only change its password (the API enforces this too).
  useEffect(() => {
    if (me.user.must_change_password && pathname !== CHANGE_PASSWORD_PATH) router.replace(CHANGE_PASSWORD_PATH);
  }, [me.user.must_change_password, pathname, router]);

  const signOut = useCallback(async (reason: "logged_out" | "idle" = "logged_out") => {
    try {
      await logout();
    } catch {
      // The session may already be gone; signing out locally is what matters.
    }
    // Full navigation on purpose: drops all client state from the ended session.
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    window.location.assign(`/login?reason=${reason}`);
  }, []);

  const refresh = useCallback(async () => setMe(await getMe()), []);

  useIdleLogout(me.session.idle_timeout_minutes, () => void signOut("idle"), () => void getMe().catch(() => {}));

  const value = useMemo<SessionValue>(() => ({
    me,
    user: me.user,
    hasPermission: (permission) => me.permissions.includes(permission),
    refresh,
    signOut,
  }), [me, refresh, signOut]);

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}
