import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  test: {
    environment: "jsdom",
    // server/: the production web server (Node environment, set per file).
    include: ["src/**/*.test.{ts,tsx}", "server/**/*.test.mjs"],
    restoreMocks: true,
  },
});
