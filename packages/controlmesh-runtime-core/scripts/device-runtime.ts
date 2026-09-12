import { openDeviceRuntime } from "../src/device-runtime-config";
import { serveRuntimeControl } from "../src/stdio-control";
import { RuntimeConflict } from "../src/value";

const daemon = process.argv[3] === "--daemon";
if (process.argv.length !== 3 && !(process.argv.length === 4 && daemon)) {
  console.error("Usage: bun scripts/device-runtime.ts /absolute/private-config.json [--daemon]\nPrivate coordinator or native worker; --daemon enables persistent scheduling and survives stdin EOF.");
  process.exit(2);
}
let owned: ReturnType<typeof openDeviceRuntime> | undefined;
try {
  owned = openDeviceRuntime(process.argv[2]);
  if (daemon) owned.startDaemon();
  await serveRuntimeControl(owned.control, owned, { keep_alive: daemon });
} catch (error) {
  console.error(JSON.stringify({ error: error instanceof RuntimeConflict ? error.code : "device_runtime_startup_failed" }));
  process.exitCode = 2;
} finally { await owned?.close(); }
