"use client";

import { Printer, UserRound } from "lucide-react";
import QRCode from "qrcode";
import { useEffect, useRef, useState } from "react";
import { createPortal, flushSync } from "react-dom";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { errorMessage } from "@/lib/api/client";
import { type IssuedPass, recordBadgePrint } from "@/lib/api/passes";
import { photoUrl } from "@/lib/api/photos";
import { formatDateTime } from "@/lib/format";

/**
 * The printed visitor badge: a CR80 card (54 × 86 mm, portrait), the common size
 * for badge printers and card holders. Change BADGE_SIZE in globals.css for
 * other label stock. Only what the gate needs is printed: no ID number, phone or
 * address. The QR holds only the random pass token.
 *
 * The visit's photo (taken at check-in) is printed so the gate can match badge
 * to face. It is the stored photo, loaded through the API like everywhere else;
 * without one (skipped, or it cannot be loaded) the badge says so and still prints.
 *
 * Printing uses the browser's print dialog. The badge is rendered into a
 * separate element directly under <body> that is the only thing printed (see
 * globals.css, "badge-print-root").
 */
export function useQrDataUrl(text: string | null): string | null {
  const [url, setUrl] = useState<{ text: string; url: string } | null>(null);
  useEffect(() => {
    if (!text) return;
    let current = true;
    // Error correction M: survives a scuffed or slightly creased badge.
    QRCode.toDataURL(text, { errorCorrectionLevel: "M", margin: 2, width: 480 })
      .then((dataUrl) => { if (current) setUrl({ text, url: dataUrl }); })
      .catch(() => {});
    return () => { current = false; };
  }, [text]);
  return url && url.text === text ? url.url : null;
}

type BadgePhoto = { url: string } | "none" | "failed";

/** Names longer than this are printed one size smaller (see .badge-name[data-long]). */
const LONG_NAME = 24;

function BadgeCard({ issued, qr, photo, onPhotoError, onScreen = false }: {
  issued: IssuedPass;
  qr: string | null;
  photo: BadgePhoto;
  onPhotoError: () => void;
  onScreen?: boolean;
}) {
  const b = issued.badge;
  const id = (name: string) => (onScreen ? name : undefined);
  return (
    <div className="badge-card" data-testid={id("badge-card")}>
      <p className="badge-org">{b.organization}</p>
      <p className="badge-band">VISITOR</p>
      <div className="badge-id">
        {typeof photo === "object" ? (
          // eslint-disable-next-line @next/next/no-img-element -- authorised API image; must not go through the image optimiser/cache
          <img className="badge-photo" src={photo.url} alt={`Photo of ${b.visitor_name}`} onError={onPhotoError}
               data-testid={id("badge-photo")} />
        ) : (
          <div className="badge-photo badge-photo-none" data-testid={id("badge-no-photo")}>
            <UserRound aria-hidden="true" />
            {photo === "failed" ? "Photo unavailable" : "No photo"}
          </div>
        )}
        <div className="badge-who">
          <p className="badge-name" data-long={b.visitor_name.length > LONG_NAME ? "" : undefined}
             data-testid={id("badge-name")}>{b.visitor_name}</p>
          <p className="badge-number" data-testid={id("badge-visit-number")}>{b.visit_number}</p>
          {b.gate_name && <p className="badge-gate">{b.gate_name}</p>}
        </div>
      </div>
      <dl className="badge-facts">
        <div><dt>Host</dt><dd>{b.host_name ?? "—"}</dd></div>
        <div><dt>Dept.</dt><dd>{b.department_name ?? "—"}</dd></div>
        <div><dt>In</dt><dd>{formatDateTime(b.check_in_at)}</dd></div>
      </dl>
      {/* eslint-disable-next-line @next/next/no-img-element -- generated data URL */}
      {qr && <img className="badge-qr" src={qr} alt="Visitor pass QR code" data-testid={id("badge-qr")} />}
      <p className="badge-foot">Valid until {formatDateTime(b.valid_until)}. Wear visibly; return at exit.</p>
    </div>
  );
}

/** Longest wait for the photo before printing without it (it is normally already loaded for the preview). */
const PHOTO_WAIT_MS = 5000;

/** Resolves once the image has loaded (true) or failed / taken too long (false). */
function imageReady(img: HTMLImageElement): Promise<boolean> {
  if (img.complete) return Promise.resolve(img.naturalWidth > 0);
  return new Promise((resolve) => {
    const timer = setTimeout(() => resolve(false), PHOTO_WAIT_MS);
    img.decode().then(() => resolve(true), () => resolve(false)).finally(() => clearTimeout(timer));
  });
}

/**
 * `photoId`: the visit's photo (null when the guard continued without one).
 * `prominent`: printing is the main next step on the screen (check-in done), so the button is large.
 */
export function BadgePreview({ issued, visitId, photoId, prominent = false }: {
  issued: IssuedPass;
  visitId: string;
  photoId: string | null;
  prominent?: boolean;
}) {
  const qr = useQrDataUrl(issued.qr_text);
  const [printRoot, setPrintRoot] = useState<HTMLElement | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [failedPhotoId, setFailedPhotoId] = useState<string | null>(null);
  const printArea = useRef<HTMLDivElement>(null);
  const photo: BadgePhoto = !photoId ? "none" : failedPhotoId === photoId ? "failed" : { url: photoUrl(photoId) };
  const onPhotoError = () => setFailedPhotoId(photoId);

  useEffect(() => {
    // Print badge is the next step: focus it once the QR is ready (it is disabled until then, so
    // autoFocus on mount could never take effect).
    if (qr) printArea.current?.querySelector("button")?.focus();
  }, [qr]);

  useEffect(() => {
    const root = document.createElement("div");
    root.className = "badge-print-root";
    document.body.appendChild(root);
    // The print element only exists in the browser; it is attached once after mounting.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setPrintRoot(root);
    return () => root.remove();
  }, []);

  async function print() {
    setError(null);
    // Recorded before the dialog opens: the browser cannot tell whether paper actually came out.
    try {
      await recordBadgePrint(visitId);
    } catch (e) {
      setError(errorMessage(e));
      return;
    }
    // The printed copy must show the photo, not a half-loaded or broken image: wait for it, and
    // print the "Photo unavailable" placeholder if it cannot be loaded.
    const img = printRoot?.querySelector<HTMLImageElement>("img.badge-photo");
    if (img && !(await imageReady(img))) flushSync(() => setFailedPhotoId(photoId));
    window.print();
  }

  return (
    <div className="space-y-3">
      {error && <Alert tone="danger">{error}</Alert>}
      <div className="flex justify-center rounded-lg bg-canvas p-4">
        <div className="badge-screen"><BadgeCard issued={issued} qr={qr} photo={photo} onPhotoError={onPhotoError} onScreen /></div>
      </div>
      <div ref={printArea} className="flex justify-center">
        <Button onClick={() => void print()} disabled={!qr} size={prominent ? "lg" : "md"}
                className={prominent ? "w-full" : ""}>
          {prominent && <Printer aria-hidden="true" />}
          Print badge
        </Button>
      </div>
      {printRoot && createPortal(<BadgeCard issued={issued} qr={qr} photo={photo} onPhotoError={onPhotoError} />, printRoot)}
    </div>
  );
}
