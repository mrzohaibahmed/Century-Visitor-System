"use client";

import { Camera, CameraOff, Check, LoaderCircle, RotateCcw, Video } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { errorMessage } from "@/lib/api/client";
import { captureGateCameraPhoto } from "@/lib/api/gateCameras";

type State =
  | { kind: "idle" }
  | { kind: "capturing" }
  | { kind: "captured"; blob: Blob; url: string }
  | { kind: "problem"; message: string };

/**
 * The gate's fixed camera (Hikvision) as the photo source: take photo → preview → retake or confirm.
 * The server takes the picture with the camera of this session's gate; the browser never talks to the
 * camera and never names it. The picture is only a preview, kept in memory: `onConfirm` uploads it the
 * same way as a webcam photo. The camera is only asked when the guard presses the button.
 */
export function GateCameraCapture({ onConfirm, onUseWebcam, confirmLabel = "Use this photo" }: {
  /** Uploads the photo. A rejection is shown and the photo is kept for another try. */
  onConfirm: (photo: Blob) => Promise<void>;
  /** Switch to the browser webcam (always possible, e.g. when the gate camera fails). */
  onUseWebcam: () => void;
  confirmLabel?: string;
}) {
  const [state, setState] = useState<State>({ kind: "idle" });
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const busy = useRef(false);                        // one picture at a time, even on a double click
  const urlRef = useRef<string | null>(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);   // leaving the step discards an unused picture
    };
  }, []);

  function forget() {
    if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    urlRef.current = null;
  }

  async function take() {
    if (busy.current) return;
    busy.current = true;
    forget();                                        // Retake: the previous picture is dropped
    setUploadError(null);
    setState({ kind: "capturing" });
    try {
      const blob = await captureGateCameraPhoto();
      if (!mounted.current) return;
      urlRef.current = URL.createObjectURL(blob);
      setState({ kind: "captured", blob, url: urlRef.current });
    } catch (error) {
      if (mounted.current) setState({ kind: "problem", message: errorMessage(error) });
    } finally {
      busy.current = false;
    }
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
        {(state.kind === "idle" || state.kind === "problem") && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 p-6 text-center text-white/75">
            {state.kind === "problem"
              ? <CameraOff aria-hidden="true" className="size-10" />
              : <Camera aria-hidden="true" className="size-10" />}
            <p className="text-sm font-medium">Ask the visitor to face the gate camera.</p>
          </div>
        )}
        {capturing && (
          <div role="status" className="absolute inset-0 flex flex-col items-center justify-center gap-3 text-white/85">
            <LoaderCircle aria-hidden="true" className="size-8 animate-spin" />
            <p className="text-sm font-medium">Taking the photo…</p>
          </div>
        )}
      </div>

      <div className="flex flex-col-reverse gap-3 sm:flex-row sm:justify-center">
        {state.kind !== "captured" && (
          <Button type="button" size="lg" onClick={() => void take()} loading={capturing}>
            {!capturing && (state.kind === "problem" ? <RotateCcw aria-hidden="true" /> : <Camera aria-hidden="true" />)}
            {state.kind === "problem" ? "Try the gate camera again" : "Take photo with gate camera"}
          </Button>
        )}
        {state.kind === "captured" && (
          <>
            <Button type="button" variant="secondary" size="lg" onClick={() => void take()} disabled={uploading}>
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
