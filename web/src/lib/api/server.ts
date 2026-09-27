import { cookies } from "next/headers";

import type { Me } from "./auth";

const API_INTERNAL_URL = process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000";

/**
 * Server-side session check for layouts: asks the API who the caller is,
 * forwarding the browser's cookies. Returns null when not logged in.
 * The API remains the authority; this only decides what to render.
 */
export async function getServerSession(): Promise<Me | null> {
  const cookieHeader = (await cookies()).toString();
  if (!cookieHeader) return null;
  let response: Response;
  try {
    response = await fetch(`${API_INTERNAL_URL}/api/v1/auth/me`, {
      headers: { cookie: cookieHeader, accept: "application/json" },
      cache: "no-store",
    });
  } catch {
    throw new Error("The application server cannot be reached.");
  }
  if (response.status === 401) return null;
  if (!response.ok) throw new Error(`Session check failed (${response.status}).`);
  return (await response.json()) as Me;
}
