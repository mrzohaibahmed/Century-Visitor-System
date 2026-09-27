"use client";

import { useEffect, useRef } from "react";

const ACTIVITY_EVENTS = ["pointerdown", "keydown", "mousemove", "wheel", "touchstart"] as const;
const CHECK_EVERY_MS = 15_000;

/**
 * Mirrors the server's idle timeout in the browser.
 *
 * - After `idleMinutes` without keyboard/mouse input, `onIdle` runs (sign out).
 * - While the user IS active, `keepAlive` is called at most every few minutes so
 *   the server-side idle clock follows real activity (pages without API calls
 *   would otherwise let the server session lapse under an active user).
 * The server enforces the timeout regardless; this only keeps UX and server in step.
 */
export function useIdleLogout(idleMinutes: number, onIdle: () => void, keepAlive: () => void) {
  const handlers = useRef({ onIdle, keepAlive });
  useEffect(() => {
    handlers.current = { onIdle, keepAlive };
  });

  useEffect(() => {
    const idleMs = idleMinutes * 60_000;
    const keepAliveMs = Math.min(5 * 60_000, Math.max(idleMs / 3, 30_000));
    let lastActivity = Date.now();
    let lastKeepAlive = Date.now();
    let fired = false;

    const onActivity = () => {
      lastActivity = Date.now();
      if (lastActivity - lastKeepAlive >= keepAliveMs) {
        lastKeepAlive = lastActivity;
        handlers.current.keepAlive();
      }
    };
    const timer = window.setInterval(() => {
      if (!fired && Date.now() - lastActivity >= idleMs) {
        fired = true;
        handlers.current.onIdle();
      }
    }, CHECK_EVERY_MS);

    ACTIVITY_EVENTS.forEach((name) => window.addEventListener(name, onActivity, { passive: true }));
    return () => {
      window.clearInterval(timer);
      ACTIVITY_EVENTS.forEach((name) => window.removeEventListener(name, onActivity));
    };
  }, [idleMinutes]);
}
