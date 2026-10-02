/**
 * The client-identity trust boundary of the production web server (server.mjs).
 *
 * This server is the first hop browsers reach: nothing in front of it can vouch for a forwarding
 * header, so every forwarding header a browser sends is dropped, and X-Forwarded-For is set to
 * exactly one address, the TCP peer of the browser's connection. Next.js forwards /api/* to FastAPI
 * with the request's headers as they are (next.config.ts rewrite), and FastAPI believes
 * X-Forwarded-For only from its loopback peer (backend/app/core/net.py). So the client IP behind
 * rate limits, audit records and sessions is the real socket address, never a browser's claim.
 *
 * X-Forwarded-Host/-Proto/-Port are dropped too (not set): Next.js fills them in itself from the
 * Host header and the connection, as it does under `next start`.
 */

/** Forwarding headers a browser could use to claim another identity (lower case, as Node keys them). */
export const CLIENT_FORWARDING_HEADERS = Object.freeze([
  "x-forwarded-for",
  "x-forwarded-host",
  "x-forwarded-proto",
  "x-forwarded-port",
  "forwarded",
  "x-real-ip",
]);

const IPV4_MAPPED = /^::ffff:(\d{1,3}(?:\.\d{1,3}){3})$/i;

/**
 * The socket address as the backend writes addresses: an IPv4-mapped IPv6 address (what Node
 * reports on a dual-stack listener) becomes plain IPv4, like the "127.0.0.1" in CG_TRUSTED_PROXIES.
 */
export function normalizeIp(address) {
  if (typeof address !== "string" || !address) return "";
  const mapped = IPV4_MAPPED.exec(address);
  return mapped ? mapped[1] : address;
}

/** Replaces every browser-supplied forwarding header with the authoritative X-Forwarded-For. */
export function setClientIdentity(req) {
  const ip = normalizeIp(req.socket?.remoteAddress);
  // Node lower-cases header names in req.headers and joins repeated X-Forwarded-For lines into one
  // value, so deleting the lower-case keys removes every spelling and every copy.
  for (const name of CLIENT_FORWARDING_HEADERS) delete req.headers[name];
  if (Array.isArray(req.rawHeaders)) {
    const raw = [];
    for (let i = 0; i < req.rawHeaders.length; i += 2) {
      if (!CLIENT_FORWARDING_HEADERS.includes(String(req.rawHeaders[i]).toLowerCase())) {
        raw.push(req.rawHeaders[i], req.rawHeaders[i + 1]);
      }
    }
    if (ip) raw.push("X-Forwarded-For", ip);
    req.rawHeaders = raw;
  }
  // No address (the connection is already gone): no header at all, so FastAPI falls back to its peer.
  if (ip) req.headers["x-forwarded-for"] = ip;
  return ip;
}
