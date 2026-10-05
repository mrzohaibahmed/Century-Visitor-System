"use client";

import jsQR from "jsqr";
import { Camera, CameraOff, LoaderCircle, RotateCcw, ScanLine, Video } from "lucide-react";
import { type ReactNode, useEffect, useRef, useState } from "react";

import { asProblem, CAMERA_MESSAGES, type CameraProblem, openCamera, stopCamera } from "@/components/camera/camera";
import { useGateCameraLive } from "@/components/camera/useGateCameraLive";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Skeleton";
import { sessionGateCamera } from "@/lib/api/gateCameras";
import { looksLikePass } from "@/lib/api/passes";

/** Frames per second decoded; enough for a badge held up to the webcam, light on the gate PC. */
const SCAN_INTERVAL_MS = 150;
/** Frames are decoded at this width at most (faster, and plenty for a 30 mm QR). */
const DECODE_WIDTH = 640;
/** The gate camera is further away: its frames keep more detail, so a badge held up to it still reads. */
const GATE_DECODE_WIDTH = 1280;

/** A QR decoder reusing one canvas. Returns the text of the QR code in the image, if any. */
function useQrDecoder() {
  const ref = useRef<{ canvas: HTMLCanvasElement; context: CanvasRenderingContext2D | null } | null>(null);
  return (image: CanvasImageSource, width: number, height: number, maxWidth: number): string | null => {
    if (!ref.current) {
      const canvas = document.createElement("canvas");
      ref.current = { canvas, context: canvas.getContext("2d", { willReadFrequently: true }) };
    }
    const { canvas, context } = ref.current;
    if (!context || !width || !height) return null;
    const scale = Math.min(1, maxWidth / width);
    canvas.width = Math.round(width * scale);
    canvas.height = Math.round(height * scale);
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    const pixels = context.getImageData(0, 0, canvas.width, canvas.height);
    return jsQR(pixels.data, pixels.width, pixels.height, { inversionAttempts: "dontInvert" })?.data || null;
  };
}

/** Aim here: corner guides, the middle stays clear for the camera image. */
function AimGuide() {
  return (
    <div aria-hidden="true" className="pointer-events-none absolute inset-[18%]">
      <span className="absolute top-0 left-0 size-8 rounded-tl-xl border-t-4 border-l-4 border-white/80" />
      <span className="absolute top-0 right-0 size-8 rounded-tr-xl border-t-4 border-r-4 border-white/80" />
      <span className="absolute bottom-0 left-0 size-8 rounded-bl-xl border-b-4 border-l-4 border-white/80" />
      <span className="absolute right-0 bottom-0 size-8 rounded-br-xl border-r-4 border-b-4 border-white/80" />
    </div>
  );
}

function ReadyToScan({ camera }: { camera: string }) {
  return (
    <div role="status" className="flex items-start gap-3">
      <ScanLine aria-hidden="true" className="mt-0.5 size-5 shrink-0 text-brand-700" />
      <p className="text-sm text-ink-muted">
        <span className="block font-semibold text-ink">Ready to scan</span>
        Hold the QR code on the visitor&apos;s badge in front of the {camera}.
      </p>
    </div>
  );
}

const NOT_A_PASS = "That code is not a Century Gate visitor pass.";

/**
 * Reads a visitor pass QR. When this session's gate has a camera, it is used first (as for the
 * check-in photo), with the webcam one click away; otherwise the webcam. Decoding happens in the
 * browser with jsQR (Edge/Chrome on Windows have no built-in BarcodeDetector); the text is only
 * handed to onScan, and the server decides what it means.
 */
export function QrScanner({ onScan, onCancel }: { onScan: (text: string) => void; onCancel: () => void }) {
  // Asking does not contact the camera; any problem simply means the webcam.
  const [gateCamera, setGateCamera] = useState<"checking" | "available" | "none">("checking");
  const [source, setSource] = useState<"gate" | "webcam">("gate");

  useEffect(() => {
    let current = true;
    sessionGateCamera()
      .then((r) => { if (current) setGateCamera(r.available ? "available" : "none"); })
      .catch(() => { if (current) setGateCamera("none"); });
    return () => { current = false; };
  }, []);

  if (gateCamera === "checking") {
    return (
      <div className="space-y-4" data-testid="qr-scanner">
        <div role="status" className="mx-auto aspect-[4/3] w-full max-w-md">
          <span className="sr-only">Checking for a gate camera…</span>
          <Skeleton className="size-full rounded-2xl" />
        </div>
        <div className="flex justify-end">
          <Button variant="secondary" size="lg" onClick={onCancel}>Cancel</Button>
        </div>
      </div>
    );
  }
  if (gateCamera === "available" && source === "gate") {
    return <GateQrScanner onScan={onScan} onCancel={onCancel} onUseWebcam={() => setSource("webcam")} />;
  }
  return (
    <WebcamQrScanner onScan={onScan} onCancel={onCancel} extra={gateCamera === "available" && (
      <Button variant="ghost" size="lg" onClick={() => setSource("gate")}>
        <Camera aria-hidden="true" />
        Use the gate camera instead
      </Button>
    )} />
  );
}

/**
 * The gate's fixed camera: its live view (frames from the server, see useGateCameraLive) is decoded
 * frame by frame. The live view stops as soon as a pass is read and when the scanner closes.
 */
function GateQrScanner({ onScan, onCancel, onUseWebcam }: {
  onScan: (text: string) => void;
  onCancel: () => void;
  onUseWebcam: () => void;
}) {
  const [problem, setProblem] = useState<string | null>(null);
  const [notAPass, setNotAPass] = useState(false);
  const read = useRef(false);
  const decode = useQrDecoder();
  const { frame, start, stop } = useGateCameraLive({
    onFrame: async (blob) => {
      if (read.current) return;
      const bitmap = await createImageBitmap(blob).catch(() => null);
      if (!bitmap) return;
      let text: string | null;
      try {
        text = decode(bitmap, bitmap.width, bitmap.height, GATE_DECODE_WIDTH);
      } finally {
        bitmap.close();
      }
      if (!text) return;
      if (!looksLikePass(text)) return setNotAPass(true);
      read.current = true;
      void stop();                                   // not awaited: this frame is still being handled
      onScan(text);
    },
    onError: setProblem,
  });

  useEffect(() => {
    start();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- start once per mount
  }, []);

  return (
    <div className="space-y-4" data-testid="qr-scanner">
      {problem ? (
        <Alert tone="danger" title="Gate camera not available">
          <p>{problem}</p>
          <p className="mt-1">You can use the webcam, or type the visit number in the box on the check-out page.</p>
        </Alert>
      ) : (
        <ReadyToScan camera="gate camera" />
      )}
      {notAPass && !problem && <Alert tone="warn">{NOT_A_PASS}</Alert>}
      <div className="relative mx-auto aspect-[4/3] w-full max-w-md overflow-hidden rounded-2xl bg-brand-900">
        {frame && !problem && (
          // eslint-disable-next-line @next/next/no-img-element -- live frame from the server, not an asset
          <img src={frame} alt="Live view from the gate camera" className="size-full object-cover"
               data-testid="gate-scanner-live" />
        )}
        {problem ? (
          <div aria-hidden="true" className="absolute inset-0 flex items-center justify-center text-white/70">
            <CameraOff className="size-10" />
          </div>
        ) : frame ? (
          <AimGuide />
        ) : (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 text-white/75">
            <LoaderCircle aria-hidden="true" className="size-8 animate-spin" />
            <p className="text-sm font-medium">Connecting to the gate camera…</p>
          </div>
        )}
      </div>
      <div className="flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
        <Button variant="ghost" size="lg" onClick={onUseWebcam}>
          <Video aria-hidden="true" />
          Use webcam
        </Button>
        <Button variant="secondary" size="lg" onClick={onCancel}>Cancel</Button>
        {problem && (
          <Button size="lg" onClick={() => { setProblem(null); start(); }}>
            <RotateCcw aria-hidden="true" />
            Try again
          </Button>
        )}
      </div>
    </div>
  );
}

/** The browser webcam. The camera is released as soon as a pass is read and when the scanner closes. */
function WebcamQrScanner({ onScan, onCancel, extra }: {
  onScan: (text: string) => void;
  onCancel: () => void;
  extra?: ReactNode;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [problem, setProblem] = useState<CameraProblem | null>(null);
  const [notAPass, setNotAPass] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const onScanRef = useRef(onScan);
  useEffect(() => { onScanRef.current = onScan; });
  const decode = useQrDecoder();
  const decodeRef = useRef(decode);
  useEffect(() => { decodeRef.current = decode; });

  useEffect(() => {
    let stream: MediaStream | null = null;
    let timer: ReturnType<typeof setInterval> | null = null;
    let active = true;

    function stop() {
      active = false;
      if (timer) clearInterval(timer);
      stopCamera(stream);
      stream = null;
    }

    function decodeFrame() {
      const video = videoRef.current;
      if (!active || !video || video.readyState < 2 || !video.videoWidth) return;
      const text = decodeRef.current(video, video.videoWidth, video.videoHeight, DECODE_WIDTH);
      if (!text) return;
      if (!looksLikePass(text)) return setNotAPass(true);
      stop();
      onScanRef.current(text);
    }

    openCamera("environment")
      .then(async (s) => {
        if (!active) return stopCamera(s);
        stream = s;
        const video = videoRef.current;
        if (video) {
          video.srcObject = s;
          await Promise.resolve(video.play()).catch(() => {});
        }
        timer = setInterval(decodeFrame, SCAN_INTERVAL_MS);
      })
      .catch((error) => { if (active) setProblem(asProblem(error)); });

    return stop;
  }, [attempt]);

  return (
    <div className="space-y-4" data-testid="qr-scanner">
      {problem ? (
        <Alert tone="danger" title="Camera not available">
          <p>{CAMERA_MESSAGES[problem]}</p>
          <p className="mt-1">You can also type the visit number in the box on the check-out page.</p>
        </Alert>
      ) : (
        <ReadyToScan camera="camera" />
      )}
      {notAPass && !problem && <Alert tone="warn">{NOT_A_PASS}</Alert>}
      <div className="relative mx-auto aspect-[4/3] w-full max-w-md overflow-hidden rounded-2xl bg-brand-900">
        {/* Shown like a mirror, so the badge moves the way the hand does. Display only: the QR is read from the camera's own frames. */}
        <video ref={videoRef} muted playsInline aria-label="QR scanner camera" className="size-full -scale-x-100 object-cover" />
        {problem ? (
          <div aria-hidden="true" className="absolute inset-0 flex items-center justify-center text-white/70">
            <CameraOff className="size-10" />
          </div>
        ) : (
          <AimGuide />
        )}
      </div>
      <div className="flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
        {extra}
        <Button variant="secondary" size="lg" onClick={onCancel}>Cancel</Button>
        {problem && (
          <Button size="lg" onClick={() => { setProblem(null); setAttempt((n) => n + 1); }}>
            <RotateCcw aria-hidden="true" />
            Try again
          </Button>
        )}
      </div>
    </div>
  );
}
