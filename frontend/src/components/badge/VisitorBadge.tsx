"use client";

import { Printer } from "lucide-react";
import QRCode from "qrcode";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { errorMessage } from "@/lib/api/client";
import { type IssuedPass, recordBadgePrint } from "@/lib/api/passes";
import { formatDateTime } from "@/lib/format";

/**
 * The printed visitor badge: a CR80 card (54 × 86 mm, portrait), the common size
 * for badge printers and card holders. Change BADGE_SIZE in globals.css for
 * other label stock. Only what the gate needs is printed: no ID number, phone or
 * address. The QR holds only the random pass token.
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

function BadgeCard({ issued, qr, onScreen = false }: { issued: IssuedPass; qr: string | null; onScreen?: boolean }) {
  const b = issued.badge;
  const id = (name: string) => (onScreen ? name : undefined);
  return (
    <div className="badge-card" data-testid={id("badge-card")}>
      <p className="badge-org">{b.organization}</p>
      <p className="badge-band">VISITOR</p>
      <p className="badge-name" data-testid={id("badge-name")}>{b.visitor_name}</p>
      <p className="badge-number" data-testid={id("badge-visit-number")}>{b.visit_number}</p>
      <dl className="badge-facts">
        <div><dt>Host</dt><dd>{b.host_name ?? "—"}</dd></div>
        <div><dt>Dept.</dt><dd>{b.department_name ?? "—"}</dd></div>
        <div><dt>In</dt><dd>{formatDateTime(b.check_in_at)}{b.gate_name ? ` · ${b.gate_name}` : ""}</dd></div>
      </dl>
      {/* eslint-disable-next-line @next/next/no-img-element -- generated data URL */}
      {qr && <img className="badge-qr" src={qr} alt="Visitor pass QR code" data-testid={id("badge-qr")} />}
      <p className="badge-foot">Valid until {formatDateTime(b.valid_until)}. Wear visibly; return at exit.</p>
    </div>
  );
}

/** `prominent`: printing is the main next step on the screen (check-in done), so the button is large. */
export function BadgePreview({ issued, visitId, prominent = false }: { issued: IssuedPass; visitId: string; prominent?: boolean }) {
  const qr = useQrDataUrl(issued.qr_text);
  const [printRoot, setPrintRoot] = useState<HTMLElement | null>(null);
  const [error, setError] = useState<string | null>(null);

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
    window.print();
  }

  return (
    <div className="space-y-3">
      {error && <Alert tone="danger">{error}</Alert>}
      <div className="flex justify-center rounded-lg bg-canvas p-4">
        <div className="badge-screen"><BadgeCard issued={issued} qr={qr} onScreen /></div>
      </div>
      <div className="flex justify-center">
        <Button onClick={() => void print()} disabled={!qr} autoFocus size={prominent ? "lg" : "md"}
                className={prominent ? "w-full" : ""}>
          {prominent && <Printer aria-hidden="true" />}
          Print badge
        </Button>
      </div>
      {printRoot && createPortal(<BadgeCard issued={issued} qr={qr} />, printRoot)}
    </div>
  );
}
