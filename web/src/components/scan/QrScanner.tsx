"use client";

import jsQR from "jsqr";
import { useEffect, useRef, useState } from "react";

import { asProblem, CAMERA_MESSAGES, type CameraProblem, openCamera, stopCamera } from "@/components/camera/camera";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { looksLikePass } from "@/lib/api/passes";

/** Frames per second decoded; enough for a badge held up to the webcam, light on the gate PC. */
const SCAN_INTERVAL_MS = 150;
/** Frames are decoded at this width at most (faster, and plenty for a 30 mm QR). */
const DECODE_WIDTH = 640;

/**
 * Reads a visitor pass QR with the webcam. Decoding happens in the browser with
 * jsQR (Edge/Chrome on Windows have no built-in BarcodeDetector); the text is
 * only handed to onScan, and the server decides what it means. The camera is
 * released as soon as a pass is read and when the scanner closes.
 */
export function QrScanner({ onScan, onCancel }: { onScan: (text: string) => void; onCancel: () => void }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [problem, setProblem] = useState<CameraProblem | null>(null);
  const [notAPass, setNotAPass] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const onScanRef = useRef(onScan);
  useEffect(() => { onScanRef.current = onScan; });

  useEffect(() => {
    let stream: MediaStream | null = null;
    let timer: ReturnType<typeof setInterval> | null = null;
    let active = true;
    const canvas = document.createElement("canvas");
    const context = canvas.getContext("2d", { willReadFrequently: true });

    function stop() {
      active = false;
      if (timer) clearInterval(timer);
      stopCamera(stream);
      stream = null;
    }

    function decodeFrame() {
      const video = videoRef.current;
      if (!active || !video || !context || video.readyState < 2 || !video.videoWidth) return;
      const scale = Math.min(1, DECODE_WIDTH / video.videoWidth);
      canvas.width = Math.round(video.videoWidth * scale);
      canvas.height = Math.round(video.videoHeight * scale);
      context.drawImage(video, 0, 0, canvas.width, canvas.height);
      const image = context.getImageData(0, 0, canvas.width, canvas.height);
      const code = jsQR(image.data, image.width, image.height, { inversionAttempts: "dontInvert" });
      if (!code?.data) return;
      if (!looksLikePass(code.data)) return setNotAPass(true);
      stop();
      onScanRef.current(code.data);
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
    <div className="space-y-3" data-testid="qr-scanner">
      {problem ? (
        <Alert tone="danger">{CAMERA_MESSAGES[problem]}</Alert>
      ) : (
        <p className="text-sm text-ink-muted">Hold the QR code on the visitor&apos;s badge in front of the camera.</p>
      )}
      {notAPass && !problem && <Alert tone="warn">That code is not a Century Gate visitor pass.</Alert>}
      <div className="relative mx-auto aspect-[4/3] w-full max-w-md overflow-hidden rounded-lg bg-brand-900">
        <video ref={videoRef} muted playsInline aria-label="QR scanner camera" className="size-full object-cover" />
        <div aria-hidden="true" className="pointer-events-none absolute inset-[18%] rounded-lg border-4 border-white/70" />
      </div>
      <div className="flex justify-end gap-2">
        {problem && (
          <Button variant="secondary" onClick={() => { setProblem(null); setAttempt((n) => n + 1); }}>Try again</Button>
        )}
        <Button variant="secondary" onClick={onCancel}>Cancel</Button>
      </div>
    </div>
  );
}
