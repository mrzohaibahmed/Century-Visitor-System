import type { NextConfig } from "next";

/**
 * The browser always calls the API on the SAME origin under /api/*.
 * - Production: the reverse proxy sends /api/* to FastAPI before it reaches Next.js.
 * - Development: this rewrite forwards /api/* to the local FastAPI server.
 * Next.js never holds database credentials; it only knows the API's internal URL.
 */
const API_INTERNAL_URL = process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000";

const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "same-origin" },
  // Camera for visitor photos (Phase 4) on this origin only; nothing else.
  { key: "Permissions-Policy", value: "camera=(self), microphone=(), geolocation=(), payment=(), usb=()" },
  // A strict nonce-based Content-Security-Policy is added in production hardening (Phase 7).
];

const nextConfig: NextConfig = {
  poweredByHeader: false,
  reactStrictMode: true,
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_INTERNAL_URL}/api/:path*` }];
  },
};

export default nextConfig;
