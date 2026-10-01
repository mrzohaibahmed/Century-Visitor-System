"use client";

import { useEffect, useRef, useState } from "react";

import { ApiError, errorMessage } from "@/lib/api/client";
import { gateCameraPreviewFrame } from "@/lib/api/gateCameras";

/** Shortest time between two live-view frames (the camera is asked one frame at a time). */
export const FRAME_INTERVAL_MS = 150;
/** Wait before asking again when the camera is busy (e.g. an administrator's test). */
const BUSY_RETRY_MS = 1000;

type LiveRun = { stop: (abort: boolean) => void; done: Promise<void> };

/**
 * Live view from this session's gate camera: frames are asked from the server one after another
 * (the browser never talks to the camera) and shown as `frame`, an object URL released when the
 * next one arrives or the component goes away. Frames are never uploaded or stored.
 *
 * `onFrame` (optional) sees each frame before the next is asked for, e.g. to look for a QR code.
 * `onError` is called once when the live view stops on a problem (a busy camera is waited for).
 * Nothing starts until `start()`; leaving the component stops the live view.
 */
export function useGateCameraLive({ onFrame, onError }: {
  onFrame?: (frame: Blob) => void | Promise<void>;
  onError: (message: string) => void;
}) {
  const [frame, setFrame] = useState<string | null>(null);
  const frameRef = useRef<string | null>(null);
  const live = useRef<LiveRun | null>(null);
  const mounted = useRef(true);
  const callbacks = useRef({ onFrame, onError });
  useEffect(() => { callbacks.current = { onFrame, onError }; });

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      void stop(true);
      dropFrame();
    };
  }, []);

  function dropFrame() {
    if (frameRef.current) URL.revokeObjectURL(frameRef.current);
    frameRef.current = null;
    if (mounted.current) setFrame(null);
  }

  function start() {
    if (live.current) return;
    const controller = new AbortController();
    let stopped = false;
    let wake: () => void = () => {};
    const pause = (ms: number) => new Promise<void>((resolve) => {
      const timer = setTimeout(resolve, ms);
      wake = () => { clearTimeout(timer); resolve(); };
    });

    const done = (async () => {
      while (!stopped) {
        if (typeof document !== "undefined" && document.hidden) {     // nobody is looking: do not ask the camera
          await pause(BUSY_RETRY_MS);
          continue;
        }
        const started = Date.now();
        try {
          const blob = await gateCameraPreviewFrame(controller.signal);
          if (stopped || !mounted.current) return;
          const url = URL.createObjectURL(blob);
          if (frameRef.current) URL.revokeObjectURL(frameRef.current);
          frameRef.current = url;
          setFrame(url);
          // A frame that cannot be handled (e.g. not decodable) is skipped, not a camera problem.
          await Promise.resolve(callbacks.current.onFrame?.(blob)).catch(() => {});
        } catch (error) {
          if (stopped || !mounted.current) return;
          if (error instanceof ApiError && error.code === "gate_camera_busy") {
            await pause(BUSY_RETRY_MS);
            continue;
          }
          live.current = null;
          dropFrame();
          callbacks.current.onError(errorMessage(error));
          return;
        }
        await pause(Math.max(0, FRAME_INTERVAL_MS - (Date.now() - started)));
      }
    })();
    live.current = {
      stop: (abort) => { stopped = true; wake(); if (abort) controller.abort(); },
      done,
    };
  }

  /** Stops live view. Without `abort` it waits for the frame being fetched, so the camera is free again. */
  async function stop(abort = false) {
    const run = live.current;
    live.current = null;
    if (!run) return;
    run.stop(abort);
    await run.done.catch(() => {});
  }

  return { frame, start, stop };
}
