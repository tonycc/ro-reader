import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const repoRoot = join(scriptDir, "..", "..", "..");
const configDir = mkdtempSync(join(tmpdir(), "ro-workbench-http-e2e-"));
const apiPort = process.env.RO_WORKBENCH_E2E_API_PORT ?? "54321";
const child = spawn(
  "uv",
  ["run", "uvicorn", "ro_workbench_api.app:app", "--host", "127.0.0.1", "--port", apiPort, "--log-level", "warning"],
  {
    cwd: repoRoot,
    env: { ...process.env, RO_WORKBENCH_CONFIG_DIR: configDir },
    stdio: "inherit",
  },
);

let stopping = false;
function stop(signal = "SIGTERM") {
  if (stopping) return;
  stopping = true;
  child.kill(signal);
}

function cleanup() {
  rmSync(configDir, { recursive: true, force: true });
}

process.on("SIGINT", () => stop("SIGINT"));
process.on("SIGTERM", () => stop("SIGTERM"));
process.on("exit", cleanup);
child.on("error", (error) => {
  console.error(error);
  cleanup();
  process.exitCode = 1;
});
child.on("exit", (code, signal) => {
  cleanup();
  if (signal && !stopping) process.exitCode = 1;
  else process.exitCode = code ?? 0;
});
