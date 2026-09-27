import { defineConfig } from "@playwright/test";
import path from "node:path";

/**
 * End-to-end tests against a real, isolated stack:
 *   Edge (installed browser) -> Next.js dev localhost:3001 -> FastAPI :8001 -> MongoDB database "cgvms_e2e"
 * The development database and API (:8000, century_gate_vms) are never used.
 * Needs the development MongoDB replica set running (scripts/dev_mongo.py start).
 */
const API_DIR = path.resolve(__dirname, "../backend");
const PYTHON = path.join(API_DIR, ".venv", "Scripts", "python.exe");

export const E2E_ADMIN_PASSWORD = "E2e-Gatekeeper-Pass-1";

const apiEnv = {
  CG_ENVIRONMENT: "test",
  CG_MONGO_URI: process.env.CG_TEST_MONGO_URI ?? "mongodb://127.0.0.1:27018/?replicaSet=cgvms-dev",
  CG_MONGO_DB: "cgvms_e2e",
  E2E_ADMIN_PASSWORD,
};

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  timeout: 60_000,
  use: {
    // localhost, not 127.0.0.1: the Next.js dev server only serves its scripts to localhost by default.
    baseURL: "http://localhost:3001",
    channel: "msedge",
    // Edge's built-in fake webcam (a moving test pattern) for photo capture; no permission prompt.
    launchOptions: { args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"] },
    permissions: ["camera"],
    trace: "retain-on-failure",
  },
  webServer: [
    {
      // Reset the E2E database, then run the API against it.
      command: `"${PYTHON}" ../scripts/e2e_reset_db.py && "${PYTHON}" -m uvicorn app.main:create_app --factory --port 8001`,
      cwd: API_DIR,
      env: apiEnv,
      url: "http://127.0.0.1:8001/api/v1/health/ready",
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: "npx next dev -p 3001",
      env: { API_INTERNAL_URL: "http://127.0.0.1:8001" },
      url: "http://localhost:3001/login",
      reuseExistingServer: false,
      timeout: 180_000,
    },
  ],
});
