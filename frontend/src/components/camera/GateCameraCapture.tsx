"use client";

import { Camera, CameraOff, Check, LoaderCircle, RotateCcw, Video } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { errorMessage } from "@/lib/api/client";
import { captureGateCameraPhoto } from "@/lib/api/gateCameras";

import { useGateCameraLive } from "./useGateCameraLive";

type State =
  | { kind: "live" }
  | { kind: "capturing" }
  | { kind: "captured"; blob: Blob; url: string }
  | { kind: "problem"; message: string };

/**
 * The gate's fixed camera (Hikvision) as the photo source: live view → take photo → preview → retake or confirm.
 * The server talks to the camera of this session's gate; the browser never talks to the camera and never
 * names it. Live view is a series of frames asked from the server one after another (never uploaded); the
 * photo itself is a separate capture, checked like a visitor photo. The picture is kept in memory only:
 * `onConfirm` uploads it the same way as a webcam photo.
 */
export function GateCameraCapture({ onConfirm, onUseWebcam, confirmLabel = "Use this photo" }: {
  /** Uploads the photo. A rejection is shown and the photo is kept for another try. */
  onConfirm: (photo: Blob) => Promise<void>;
  /** Switch to the browser webcam (always possible, e.g. when the gate camera fails). */
  onUseWebcam: () => void;
  confirmLabel?: string;
}) {
  const [state, setState] = useState<State>({ kind: "live" });
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const busy = useRef(false);                        // one picture at a time, even on a double click
  const urlRef = useRef<string | null>(null);
  const mounted = useRef(true);
  const { frame, start: startLive, stop: stopLive } = useGateCameraLive({
    onError: (message) => setState({ kind: "problem", message }),
  });

  useEffect(() => {
    mounted.current = true;
    startLive();
    return () => {
      mounted.current = false;
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);   // leaving the step discards an unused picture
      urlRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- start once per mount
  }, []);

  function forget() {
    if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    urlRef.current = null;
  }

  async function take() {
    if (busy.current) return;
    busy.current = true;
    setUploadError(null);
    setState({ kind: "capturing" });
    try {
      await stopLive();
      const blob = await captureGateCameraPhoto();
      if (!mounted.current) return;
      forget();
      urlRef.current = URL.createObjectURL(blob);
      setState({ kind: "captured", blob, url: urlRef.current });
    } catch (error) {
      if (mounted.current) setState({ kind: "problem", message: errorMessage(error) });
    } finally {
      busy.current = false;
    }
  }

  /** Back to live view: Retake drops the picture; after a problem, the camera is asked again. */
  function goLive() {
    if (busy.current) return;
    forget();                                        // Retake: the previous picture is dropped
    setUploadError(null);
    setState({ kind: "live" });
    startLive();
  }

  async function confirm(blob: Blob) {
    setUploadError(null);
    setUploading(true);
    try {
      await onConfirm(blob);
    } catch (error) {
      if (mounted.current) setUploadError(errorMessage(error));
    } finally {
      if (mounted.current) setUploading(false);
    }
  }

  const capturing = state.kind === "capturing";
  const showFrame = (state.kind === "live" || capturing) && frame;
  return (
    <div className="space-y-4" data-testid="gate-camera-capture">
      {state.kind === "problem" && (
        <Alert tone="danger" title="Gate camera not available">
          {state.message} You can use the webcam, or continue without a photo.
        </Alert>
      )}
      {uploadError && <Alert tone="danger">The photo was not saved: {uploadError}</Alert>}

      <div className="relative mx-auto aspect-[4/3] w-full max-w-lg overflow-hidden rounded-2xl bg-brand-900 shadow-card">
        {state.kind === "captured" && (
          // eslint-disable-next-line @next/next/no-img-element -- in-memory preview from the server, not an asset
          <img src={state.url} alt="Photo from the gate camera" className="size-full object-cover" data-testid="gate-camera-photo" />
        )}
        {showFrame && (
          // eslint-disable-next-line @next/next/no-img-element -- live frame from the server, not an asset
          <img src={frame} alt="Live view from the gate camera" className="size-full object-cover"
               data-testid="gate-camera-live" />
        )}
        {state.kind === "live" && frame && (
          // Framing guide only, as on the webcam; the whole frame is captured.
          <div aria-hidden="true" className="pointer-events-none absolute inset-0 flex items-center justify-center"
               data-testid="gate-camera-guide">
            <div className="aspect-[3/4] h-3/4 rounded-[50%] border-2 border-dashed border-white/70" />
          </div>
        )}
        {state.kind === "live" && frame && (
          <span className="absolute left-3 top-3 inline-flex items-center gap-1.5 rounded-full bg-black/55 px-2.5 py-1 text-xs font-semibold text-white">
            <span aria-hidden="true" className="size-2 animate-pulse rounded-full bg-red-500" />
            Live
          </span>
        )}
        {state.kind === "live" && !frame && (
          <div role="status" className="absolute inset-0 flex flex-col items-center justify-center gap-3 p-6 text-center text-white/75">
            <LoaderCircle aria-hidden="true" className="size-8 animate-spin" />
            <p className="text-sm font-medium">Connecting to the gate camera…</p>
          </div>
        )}
        {state.kind === "problem" && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 p-6 text-center text-white/75">
            <CameraOff aria-hidden="true" className="size-10" />
            <p className="text-sm font-medium">Ask the visitor to face the gate camera.</p>
          </div>
        )}
        {capturing && (
          <div role="status" className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-black/40 text-white/90">
            <LoaderCircle aria-hidden="true" className="size-8 animate-spin" />
            <p className="text-sm font-medium">Taking the photo…</p>
          </div>
        )}
      </div>

      <div className="flex flex-col-reverse gap-3 sm:flex-row sm:justify-center">
        {(state.kind === "live" || capturing) && (
          <Button type="button" size="lg" onClick={() => void take()} loading={capturing}>
            {!capturing && <Camera aria-hidden="true" />}
            Take photo with gate camera
          </Button>
        )}
        {state.kind === "problem" && (
          <Button type="button" size="lg" onClick={goLive}>
            <RotateCcw aria-hidden="true" />
            Try the gate camera again
          </Button>
        )}
        {state.kind === "captured" && (
          <>
            <Button type="button" variant="secondary" size="lg" onClick={goLive} disabled={uploading}>
              <RotateCcw aria-hidden="true" />
              Retake
            </Button>
            <Button type="button" size="lg" onClick={() => void confirm(state.blob)} loading={uploading}>
              {!uploading && <Check aria-hidden="true" />}
              {confirmLabel}
            </Button>
          </>
        )}
      </div>
      <div className="flex justify-center">
        <Button type="button" variant={state.kind === "problem" ? "secondary" : "ghost"} onClick={onUseWebcam}
                disabled={capturing || uploading}>
          <Video aria-hidden="true" />
          Use webcam
        </Button>
      </div>
    </div>
  );
}
