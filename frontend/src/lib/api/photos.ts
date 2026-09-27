import { API_BASE, apiRequest } from "./client";

/** Mirrors app/schemas/photos.py. The image itself is only ever fetched from photoUrl(). */
export type Photo = { id: string; captured_at: string; width: number; height: number };

export function uploadVisitorPhoto(visitorId: string, image: Blob): Promise<Photo> {
  return apiRequest<Photo>(`/visitors/${encodeURIComponent(visitorId)}/photo`, { method: "POST", rawBody: image });
}

/** Same-origin URL; the API checks the session and whether this user may see this photo. */
export function photoUrl(photoId: string): string {
  return `${API_BASE}/photos/${encodeURIComponent(photoId)}`;
}
