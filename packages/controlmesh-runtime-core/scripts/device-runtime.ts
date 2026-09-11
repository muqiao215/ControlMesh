import { openDeviceRuntime } from "../src/device-runtime-config";
import { serveRuntimeControl } from "../src/stdio-control";
import { RuntimeConflict } from "../src/value";

if (process.argv.length !== 3) {
  console.error("Usage: bun scripts/device-runtime.ts /absolute/private-config.json\nPrivate candidate coordinator or native worker; JSON-lines control on stdin/stdout.");
  process.exit(2);
}
let owned: ReturnType<typeof openDeviceRuntime> | undefined;
try {
  owned = openDeviceRuntime(process.argv[2]);
  await serveRuntimeControl(owned.control, owned);
} catch (error) {
  console.error(JSON.stringify({ error: error instanceof RuntimeConflict ? error.code : "device_runtime_startup_failed" }));
  process.exitCode = 2;
} finally { await owned?.close(); }
