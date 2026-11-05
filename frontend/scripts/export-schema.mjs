// Exports the backend FastAPI OpenAPI schema to ./openapi.json.
//
// Runs the backend's `app.export_openapi` module, which serialises the
// Pydantic domain contracts into an OpenAPI document. The frontend type
// generation (`npm run gen:types`) then turns that document into
// `src/types/api.d.ts`, keeping the typed API client in lock-step with the
// backend contract (R-04.3; NFR-02).
//
// Resolution order for the Python runner is `uv run` (the backend uses uv),
// then `python`, then `py -3`. The first one that succeeds wins.

import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const frontendRoot = resolve(here, "..");
const backendRoot = resolve(frontendRoot, "..", "backend");
const outputPath = resolve(frontendRoot, "openapi.json");

if (!existsSync(backendRoot)) {
  console.error(`Backend directory not found at ${backendRoot}`);
  process.exit(1);
}

const moduleArgs = ["-m", "app.export_openapi", outputPath];

/** @type {{cmd: string, args: string[]}[]} */
const candidates = [
  { cmd: "uv", args: ["run", "python", ...moduleArgs] },
  { cmd: "python", args: moduleArgs },
  { cmd: "python3", args: moduleArgs },
  { cmd: "py", args: ["-3", ...moduleArgs] },
];

let lastError = null;
for (const { cmd, args } of candidates) {
  const result = spawnSync(cmd, args, {
    cwd: backendRoot,
    stdio: "inherit",
    shell: process.platform === "win32",
  });
  if (result.error) {
    lastError = result.error;
    continue; // runner not available, try the next one
  }
  if (result.status === 0) {
    console.log(`OpenAPI schema written to ${outputPath}`);
    process.exit(0);
  }
  // The runner ran but the export failed: surface that and stop.
  process.exit(result.status ?? 1);
}

console.error("Could not run the backend OpenAPI exporter.");
console.error("Tried: uv run python, python, python3, py -3.");
if (lastError) console.error(String(lastError));
process.exit(1);
