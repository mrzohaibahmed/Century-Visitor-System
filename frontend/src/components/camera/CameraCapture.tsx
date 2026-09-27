"use client";

import { useEffect, useRef, useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { errorMessage } from "@/lib/api/client";

import { asProblem, CAMERA_MESSAGES, type CameraProblem, openCamera, stopCamera } from "./camera";

type State =
  | { kind: "idle" }
  | { kind: "starting" }
  | { kind: "live" }
  | { kind: "captured"; blob: Blob; url: string }
  | { kind: "problem"; problem: CameraProblem };

/** Longest side of the captured image; the server scales down further and re-encodes. */
const CAPTURE_MAX_SIDE = 1280;

/**
 * Start camera → live preview → capture → preview → retake or confirm (upload).
 * The camera is released as soon as a picture is taken, and whenever the
 * component goes away (step changed, page left).
 */
export function CameraCapture({ onConfirm, confirmLabel = "Use this photo" }: {
  /** Uploads the photo. A rejection is shown and the photo is kept for another try. */
  onConfirm: (photo: Blob) => Promise<void>;
  confirmLabel?: string;
}) {
  const [state, setState] = useState<State>({ kind: "idle" });
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const urlRef = useRef<string | null>(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      stopCamera(streamRef.current);
      streamRef.current = null;
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    };
  }, []);

  function release() {
    stopCamera(streamRef.current);
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
  }

  async function start() {
    setUploadError(null);
    if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    urlRef.current = null;
    setState({ kind: "starting" });
    try {
      const stream = await openCamera("user");
      if (!mounted.current) return stopCamera(stream);          // left the page while the browser was asking
      streamRef.current = stream;
      const video = videoRef.current;
      if (video) {
        video.srcObject = stream;
        await Promise.resolve(video.play()).catch(() => {});
      }
      setState({ kind: "live" });
    } catch (error) {
      release();
      if (mounted.current) setState({ kind: "problem", problem: asProblem(error) });
    }
  }

  function capture() {
    const video = videoRef.current;
    if (!video || !video.videoWidth) return;
    const scale = Math.min(1, CAPTURE_MAX_SIDE / Math.max(video.videoWidth, video.videoHeight));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(video.videoWidth * scale);
    canvas.height = Math.round(video.videoHeight * scale);
    canvas.getContext("2d")?.drawImage(video, 0, 0, canvas.width, canvas.height);
    canvas.toBlob((blob) => {
      release();
      if (!mounted.current) return;
      if (!blob) return setState({ kind: "problem", problem: "failed" });
      urlRef.current = URL.createObjectURL(blob);
      setState({ kind: "captured", blob, url: urlRef.current });
    }, "image/jpeg", 0.9);
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

  const live = state.kind === "live" || state.kind === "starting";
  return (
    <div className="space-y-3" data-testid="camera-capture">
      {state.kind === "problem" && <Alert tone="danger">{CAMERA_MESSAGES[state.problem]}</Alert>}
      {uploadError && <Alert tone="danger">The photo was not saved: {uploadError}</Alert>}

      <div className="relative mx-auto aspect-[4/3] w-full max-w-md overflow-hidden rounded-lg bg-brand-900">
        <video ref={videoRef} muted playsInline aria-label="Camera preview"
               className={`size-full object-cover ${live ? "" : "hidden"}`} />
        {state.kind === "captured" && (
          // eslint-disable-next-line @next/next/no-img-element -- local blob preview, not an optimisable asset
          <img src={state.url} alt="Captured photo" className="size-full object-cover" data-testid="captured-photo" />
        )}
        {(state.kind === "idle" || state.kind === "problem") && (
          <p className="absolute inset-0 flex items-center justify-center p-6 text-center text-sm text-white/70">
            The camera is off.
          </p>
        )}
        {state.kind === "starting" && (
          <p className="absolute inset-0 flex items-center justify-center text-sm text-white/80">Starting camera…</p>
        )}
      </div>

      <div className="flex flex-wrap justify-center gap-2">
        {(state.kind === "idle" || state.kind === "problem") && (
          <Button type="button" onClick={() => void start()}>
            {state.kind === "problem" ? "Try the camera again" : "Start camera"}
          </Button>
        )}
        {live && (
          <Button type="button" onClick={capture} disabled={state.kind !== "live"}>Take photo</Button>
        )}
        {state.kind === "captured" && (
          <>
            <Button type="button" variant="secondary" onClick={() => void start()} disabled={uploading}>Retake</Button>
            <Button type="button" onClick={() => void confirm(state.blob)} loading={uploading}>{confirmLabel}</Button>
          </>
        )}
      </div>
    </div>
  );
}
