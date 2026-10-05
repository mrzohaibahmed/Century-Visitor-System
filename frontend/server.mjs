/**
 * Production web server: the Next.js production build behind Node's own HTTP server, so that the
 * browser's real address reaches the API (server/forwarding.mjs). Everything else is Next.js as
 * under `next start`: pages, static files, and the /api/* rewrite to FastAPI (next.config.ts).
 *
 *     node server.mjs [--hostname 127.0.0.1] [--port 6543]       (after npm run build)
 *
 * Production only: development keeps `next dev` (npm run dev). Listens on 127.0.0.1 unless told otherwise.
 */
import { createServer } from "node:http";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";

import { setClientIdentity } from "./server/forwarding.mjs";

const { values } = parseArgs({
  options: {
    hostname: { type: "string", short: "H", default: "127.0.0.1" },
    port: { type: "string", short: "p", default: process.env.PORT ?? "6543" },
  },
});
const hostname = values.hostname;
const port = Number(values.port);
if (!Number.isInteger(port) || port < 1 || port > 65535) {
  console.error(`Invalid port: ${values.port}`);
  process.exit(2);
}

// The production build only, whatever the environment says (never the development server).
process.env.NODE_ENV = "production";
const { default: next } = await import("next");

let handle;
const server = createServer((req, res) => {
  setClientIdentity(req);
  handle(req, res).catch((error) => {
    console.error("Request failed:", error);
    if (!res.headersSent) res.statusCode = 500;
    res.end();
  });
});

const app = next({ dev: false, dir: fileURLToPath(new URL(".", import.meta.url)), hostname, port, httpServer: server });
await app.prepare();
handle = app.getRequestHandler();

server.listen(port, hostname, () => {
  console.log(`> Century Gate VMS web (production) listening on http://${hostname}:${port}`);
});
