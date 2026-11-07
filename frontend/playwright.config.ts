import { defineConfig } from "@playwright/test";

// Browser runs against the stub-backed stack:
// - accessibility runs (R-09.1 to R-09.5; NFR-03, NFR-04) use the stub screen gallery in
//   harness.html and need only the Vite dev server;
// - end-to-end runs (task 10.4; R-12.2, R-12.6) also use two API servers on the deterministic
//   stub model (no AWS call): one that succeeds and one whose model always fails. Vite proxies
//   /e2e-ok and /e2e-fail to them.
function apiServer(port: number, mode: "ok" | "fail") {
  return {
    command: `uv run python -m uvicorn tests.e2e_server:app --host 127.0.0.1 --port ${port}`,
    cwd: "../backend",
    env: { E2E_BACKEND_MODE: mode },
    url: `http://127.0.0.1:${port}/healthz`,
    reuseExistingServer: true,
    timeout: 120_000,
  };
}

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  reporter: "list",
  // One worker: the ok backend keeps sessions in memory and the rate limiter is per client.
  workers: 1,
  use: { baseURL: "http://127.0.0.1:5199" },
  webServer: [
    {
      command: "npx vite --host 127.0.0.1 --port 5199 --strictPort",
      url: "http://127.0.0.1:5199/harness.html",
      reuseExistingServer: true,
      timeout: 60_000,
    },
    apiServer(8765, "ok"),
    apiServer(8766, "fail"),
  ],
});
