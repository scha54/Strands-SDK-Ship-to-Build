/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Mobile-first SPA build + Vitest unit testing (jsdom) configuration.
export default defineConfig({
  plugins: [react()],
  // End-to-end runs (task 10.4): the stub-backed API servers sit behind these prefixes.
  server: {
    proxy: {
      "/e2e-ok": {
        target: process.env.E2E_OK_URL ?? "http://127.0.0.1:8765",
        rewrite: (path) => path.replace(/^\/e2e-ok/, ""),
      },
      "/e2e-fail": {
        target: process.env.E2E_FAIL_URL ?? "http://127.0.0.1:8766",
        rewrite: (path) => path.replace(/^\/e2e-fail/, ""),
      },
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: true,
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
  },
});
