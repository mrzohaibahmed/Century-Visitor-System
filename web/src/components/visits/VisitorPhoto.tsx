"use client";

import { useState } from "react";

import { photoUrl } from "@/lib/api/photos";

/**
 * A visitor photo, loaded through the API (session + permission checked there, never cached).
 * Shows a neutral placeholder when there is no photo or the user may not see it.
 */
export function VisitorPhoto({ photoId, name, className = "size-28" }: {
  photoId: string | null | undefined;
  name: string | null | undefined;
  className?: string;
}) {
  const [failedId, setFailedId] = useState<string | null>(null);
  const failed = photoId != null && failedId === photoId;
  if (!photoId || failed) {
    return (
      <div className={`flex shrink-0 items-center justify-center rounded-lg bg-canvas text-center text-xs text-ink-muted ${className}`}
           data-testid="no-photo">
        {failed ? "Photo unavailable" : "No photo"}
      </div>
    );
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element -- authorised API image; must not go through the image optimiser/cache
    <img src={photoUrl(photoId)} alt={name ? `Photo of ${name}` : "Visitor photo"} onError={() => setFailedId(photoId)}
         className={`shrink-0 rounded-lg bg-canvas object-cover ${className}`} data-testid="visitor-photo" />
  );
}
