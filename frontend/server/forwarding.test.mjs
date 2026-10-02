// @vitest-environment node
import { once } from "node:events";
import { createServer } from "node:http";
import { connect } from "node:net";

import { describe, expect, it } from "vitest";

import { CLIENT_FORWARDING_HEADERS, normalizeIp, setClientIdentity } from "./forwarding.mjs";

/** A request as Node's HTTP server hands it over: lower-case `headers`, original spelling in `rawHeaders`. */
function fakeRequest(remoteAddress, rawHeaders = []) {
  const headers = {};
  for (let i = 0; i < rawHeaders.length; i += 2) {
    const name = rawHeaders[i].toLowerCase();
    headers[name] = name in headers ? `${headers[name]}, ${rawHeaders[i + 1]}` : rawHeaders[i + 1];
  }
  return { socket: { remoteAddress }, headers, rawHeaders: [...rawHeaders] };
}

function rawValues(req, name) {
  const out = [];
  for (let i = 0; i < req.rawHeaders.length; i += 2) {
    if (req.rawHeaders[i].toLowerCase() === name) out.push(req.rawHeaders[i + 1]);
  }
  return out;
}

describe("setClientIdentity (fake browser sockets)", () => {
  it("replaces a spoofed X-Forwarded-For with the socket address", () => {
    const req = fakeRequest("192.168.1.50", ["Host", "vms:3000", "X-Forwarded-For", "10.10.10.10"]);
    expect(setClientIdentity(req)).toBe("192.168.1.50");
    expect(req.headers["x-forwarded-for"]).toBe("192.168.1.50");
    expect(rawValues(req, "x-forwarded-for")).toEqual(["192.168.1.50"]);
    expect(JSON.stringify(req)).not.toContain("10.10.10.10");
  });

  it("adds the socket address when the browser sends none", () => {
    const req = fakeRequest("192.168.1.50", ["Host", "vms:3000"]);
    setClientIdentity(req);
    expect(req.headers["x-forwarded-for"]).toBe("192.168.1.50");
  });

  it("drops a whole chain of spoofed addresses, not just the last one", () => {
    const req = fakeRequest("192.168.1.50", ["X-Forwarded-For", "10.0.0.1, 172.16.0.5, 8.8.8.8"]);
    setClientIdentity(req);
    expect(req.headers["x-forwarded-for"]).toBe("192.168.1.50");
  });

  it("ignores the spelling and repetition of forwarding headers", () => {
    const req = fakeRequest("192.168.1.50", [
      "x-forwarded-for", "10.0.0.1", "X-FORWARDED-FOR", "10.0.0.2", "X-Forwarded-For", "10.0.0.3",
      "x-FoRwArDeD-fOr", "10.0.0.4", "X-Real-IP", "10.0.0.5", "FORWARDED", "for=10.0.0.6",
      "X-Forwarded-Host", "evil.example", "X-Forwarded-Proto", "https", "X-Forwarded-Port", "443",
    ]);
    setClientIdentity(req);
    expect(req.headers["x-forwarded-for"]).toBe("192.168.1.50");
    for (const name of CLIENT_FORWARDING_HEADERS.filter((n) => n !== "x-forwarded-for")) {
      expect(req.headers[name]).toBeUndefined();
      expect(rawValues(req, name)).toEqual([]);
    }
    expect(rawValues(req, "x-forwarded-for")).toEqual(["192.168.1.50"]);
  });

  it("keeps two clients apart", () => {
    const a = fakeRequest("192.168.1.20", ["X-Forwarded-For", "192.168.1.21"]);
    const b = fakeRequest("192.168.1.21", ["X-Forwarded-For", "192.168.1.20"]);
    setClientIdentity(a);
    setClientIdentity(b);
    expect(a.headers["x-forwarded-for"]).toBe("192.168.1.20");
    expect(b.headers["x-forwarded-for"]).toBe("192.168.1.21");
  });

  it("writes IPv4-mapped IPv6 addresses as plain IPv4, other IPv6 as is", () => {
    expect(normalizeIp("::ffff:192.168.1.50")).toBe("192.168.1.50");
    expect(normalizeIp("::FFFF:127.0.0.1")).toBe("127.0.0.1");
    expect(normalizeIp("fe80::1")).toBe("fe80::1");
    expect(normalizeIp("::1")).toBe("::1");
    const req = fakeRequest("::ffff:192.168.1.50", ["X-Forwarded-For", "10.10.10.10"]);
    setClientIdentity(req);
    expect(req.headers["x-forwarded-for"]).toBe("192.168.1.50");
  });

  it("sends no X-Forwarded-For at all when the socket has no address", () => {
    const req = fakeRequest(undefined, ["X-Forwarded-For", "10.10.10.10"]);
    expect(setClientIdentity(req)).toBe("");
    expect(req.headers["x-forwarded-for"]).toBeUndefined();
    expect(rawValues(req, "x-forwarded-for")).toEqual([]);
  });

  it("leaves every other header alone", () => {
    const req = fakeRequest("192.168.1.50", ["Cookie", "cg_session=abc; cg_csrf=def", "X-CSRF-Token", "def",
                                             "Content-Type", "application/json", "X-Forwarded-For", "1.2.3.4"]);
    setClientIdentity(req);
    expect(req.headers.cookie).toBe("cg_session=abc; cg_csrf=def");
    expect(req.headers["x-csrf-token"]).toBe("def");
    expect(req.headers["content-type"]).toBe("application/json");
  });
});

/** A raw HTTP/1.1 request on a real socket, so header spelling and repetition are exactly as written. */
async function rawRequest(port, headerLines) {
  const socket = connect(port, "127.0.0.1");
  await once(socket, "connect");
  // write, not end: a half-closed socket counts as a client that went away, and the proxy gives up.
  socket.write(`GET /api/v1/echo HTTP/1.1\r\nHost: vms:3000\r\nConnection: close\r\n${headerLines.join("\r\n")}\r\n\r\n`);
  let text = "";
  for await (const chunk of socket) text += chunk;
  return JSON.parse(text.slice(text.indexOf("\r\n\r\n") + 4));
}

describe("through a real socket and Next.js's own proxy (the /api/* rewrite)", () => {
  it("delivers only the socket address upstream", async () => {
    // Stands in for FastAPI: answers with the headers it received.
    const upstream = createServer((req, res) => {
      res.setHeader("content-type", "application/json");
      res.end(JSON.stringify(req.headers));
    });
    upstream.listen(0, "127.0.0.1");
    await once(upstream, "listening");
    // The same proxy library and options Next.js uses for external rewrites (router-utils/proxy-request.js).
    const { ProxyServer } = await import("next/dist/compiled/httpxy/index.js");
    const target = new URL(`http://127.0.0.1:${upstream.address().port}/api/v1/echo`);
    const edge = createServer((req, res) => {
      setClientIdentity(req);
      const proxy = new ProxyServer({ target, changeOrigin: true, ignorePath: true,
                                      headers: { "x-forwarded-host": req.headers.host || "" } });
      proxy.web(req, res, {}).catch((error) => res.end(JSON.stringify({ proxyError: String(error) })));
    });
    edge.listen(0, "127.0.0.1");
    await once(edge, "listening");
    try {
      const seen = await rawRequest(edge.address().port, [
        "X-FORWARDED-FOR: 10.10.10.10", "x-forwarded-for: 10.0.0.1, 172.16.0.5, 8.8.8.8",
        "X-Real-IP: 8.8.4.4", "Forwarded: for=8.8.8.8", "Cookie: cg_session=abc",
      ]);
      expect(seen["x-forwarded-for"]).toBe("127.0.0.1");
      expect(seen["x-real-ip"]).toBeUndefined();
      expect(seen.forwarded).toBeUndefined();
      expect(seen.cookie).toBe("cg_session=abc");
      expect(JSON.stringify(seen)).not.toMatch(/10\.10\.10\.10|8\.8\.8\.8|8\.8\.4\.4|10\.0\.0\.1/);
    } finally {
      edge.close();
      upstream.close();
    }
  });
});
