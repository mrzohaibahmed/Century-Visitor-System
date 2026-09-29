import type { Metadata } from "next";

import { GateCamerasManager } from "./GateCamerasManager";

export const metadata: Metadata = { title: "Gate cameras" };

export default function GateCamerasPage() {
  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-ink">Gate cameras</h1>
        <p className="mt-1 text-sm text-ink-muted">
          A Hikvision camera per gate for visitor photos. The server connects to the cameras, never this browser.
          Camera passwords are stored encrypted and are never shown. Tests use the saved settings and store nothing.
        </p>
      </div>
      <GateCamerasManager />
    </div>
  );
}
