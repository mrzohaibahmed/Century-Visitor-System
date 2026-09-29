"use client";

import { Camera, CameraOff, Check, LoaderCircle, RotateCcw } from "lucide-react";
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
  // The live preview can run a moment before the first frame arrives; until then nothing can be captured.
  const [frameReady, setFrameReady] = useState(false);
  const [notReady, setNotReady] = useState(false);
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
    setFrameReady(false);
    setNotReady(false);
    setState({ kind: "starting" });
    try {
      const stream = await openCamera("user");
      if (!mounted.current) return stopCamera(stream);          // left the page while the browser was asking
      streamRef.current = stream;
      // Unplugged (or taken by the system) while live: say so instead of showing a frozen preview.
      // Not fired when the camera is released on purpose.
      stream.getTracks().forEach((track) => {
        track.onended = () => {
          if (streamRef.current !== stream) return;
          release();
          if (mounted.current) setState({ kind: "problem", problem: "disconnected" });
        };
      });
      const video = videoRef.current;
      if (video) {
        video.srcObject = stream;
        await Promise.resolve(video.play()).catch(() => {});
      }
      setState({ kind: "live" });
      if (video?.videoWidth) setFrameReady(true);             // otherwise the video's frame events set it
    } catch (error) {
      release();
      if (mounted.current) setState({ kind: "problem", problem: asProblem(error) });
    }
  }

  function capture() {
    const video = videoRef.current;
    if (!video || !video.videoWidth) {
      // Never ignore the button silently: say so, and wait for the next frame.
      setFrameReady(false);
      setNotReady(true);
      return;
    }
    setNotReady(false);
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
  const off = state.kind === "idle" || state.kind === "problem";
  const canCapture = state.kind === "live" && frameReady;
  const markReady = (e: React.SyntheticEvent<HTMLVideoElement>) => {
    if (e.currentTarget.videoWidth) { setFrameReady(true); setNotReady(false); }
  };
  return (
    <div className="space-y-4" data-testid="camera-capture">
      {state.kind === "problem" && <Alert tone="danger" title="Camera not available">{CAMERA_MESSAGES[state.problem]}</Alert>}
      {uploadError && <Alert tone="danger">The photo was not saved: {uploadError}</Alert>}
      {notReady && <Alert tone="warn">Camera not ready, try again.</Alert>}

      <div className="relative mx-auto aspect-[4/3] w-full max-w-lg overflow-hidden rounded-2xl bg-brand-900 shadow-card">
        <video ref={videoRef} muted playsInline aria-label="Camera preview"
               onLoadedMetadata={markReady} onLoadedData={markReady} onResize={markReady}
               className={`size-full object-cover ${live ? "" : "hidden"}`} />
        {canCapture && (
          // Framing guide only; the whole frame is captured.
          <div aria-hidden="true" className="pointer-events-none absolute inset-0 flex items-center justify-center">
            <div className="aspect-[3/4] h-3/4 rounded-[50%] border-2 border-dashed border-white/70" />
          </div>
        )}
        {state.kind === "captured" && (
          // eslint-disable-next-line @next/next/no-img-element -- local blob preview, not an optimisable asset
          <img src={state.url} alt="Captured photo" className="size-full object-cover" data-testid="captured-photo" />
        )}
        {off && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 p-6 text-center text-white/75">
            {state.kind === "problem"
              ? <CameraOff aria-hidden="true" className="size-10" />
              : <Camera aria-hidden="true" className="size-10" />}
            <p className="text-sm font-medium">The camera is off.</p>
          </div>
        )}
        {live && !canCapture && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 text-white/85">
            <LoaderCircle aria-hidden="true" className="size-8 animate-spin" />
            <p className="text-sm font-medium">Starting camera…</p>
          </div>
        )}
      </div>

      <div className="flex flex-col-reverse gap-3 sm:flex-row sm:justify-center">
        {off && (
          <Button type="button" size="lg" onClick={() => void start()}>
            {state.kind === "problem" ? <RotateCcw aria-hidden="true" /> : <Camera aria-hidden="true" />}
            {state.kind === "problem" ? "Try the camera again" : "Start camera"}
          </Button>
        )}
        {live && (
          <Button type="button" size="lg" onClick={capture} disabled={!canCapture}>
            <Camera aria-hidden="true" />
            Take photo
          </Button>
        )}
        {state.kind === "captured" && (
          <>
            <Button type="button" variant="secondary" size="lg" onClick={() => void start()} disabled={uploading}>
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
    </div>
  );
}
