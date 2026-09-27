"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { getLiveness, getReadiness, type ReadyResponse } from "@/lib/api/health";

export type SystemState = "checking" | "ready" | "degraded" | "offline";

export type SystemHealth = {
  state: SystemState;
  checks: ReadyResponse["checks"] | null;
  version: string | null;
  checkedAt: Date | null;
  refresh: () => void;
};

const POLL_MS = 30_000;

/**
 * Polls the API's readiness. "degraded" = the API answers but is not ready
 * (e.g. database down); "offline" = the API itself cannot be reached.
 * Pauses while the tab is hidden.
 */
export function useSystemHealth(pollMs: number = POLL_MS): SystemHealth {
  const [state, setState] = useState<SystemState>("checking");
  const [checks, setChecks] = useState<ReadyResponse["checks"] | null>(null);
  const [version, setVersion] = useState<string | null>(null);
  const [checkedAt, setCheckedAt] = useState<Date | null>(null);
  const controller = useRef<AbortController | null>(null);

  const check = useCallback(async () => {
    controller.current?.abort();
    const current = new AbortController();
    controller.current = current;
    try {
      const [ready, live] = await Promise.all([
        getReadiness(current.signal),
        getLiveness(current.signal).catch(() => null),
      ]);
      setChecks(ready.checks);
      setVersion(live?.version ?? null);
      setState(ready.status === "ready" ? "ready" : "degraded");
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      setChecks(null);
      setState("offline");
    }
    setCheckedAt(new Date());
  }, []);

  useEffect(() => {
    // Initial check and polling: fetch results update state from the async callback.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void check();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void check();
    }, pollMs);
    const onVisible = () => document.visibilityState === "visible" && void check();
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
      controller.current?.abort();
    };
  }, [check, pollMs]);

  return { state, checks, version, checkedAt, refresh: () => void check() };
}
