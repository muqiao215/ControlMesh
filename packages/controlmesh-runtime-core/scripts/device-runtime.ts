import { openDeviceRuntime } from "../src/device-runtime-config";
import { serveRuntimeControl } from "../src/stdio-control";
import { RuntimeConflict } from "../src/value";

const args = process.argv.slice(2), config = args.shift();
let daemon = false, socket: string | undefined, valid = Boolean(config);
while (args.length) {
  const flag = args.shift();
  if (flag === "--daemon" && !daemon) daemon = true;
  else if (flag === "--socket" && socket === undefined && args[0] && !args[0].startsWith("--")) socket = args.shift();
  else { valid = false; break; }
}
if (!valid) {
  console.error("Usage: bun scripts/device-runtime.ts /absolute/private-config.json [--daemon] [--socket /absolute/private/runtime.sock]");
  process.exit(2);
}
if (socket) {
  const { startDeviceRuntimeService } = await import("../src/device-runtime-service");
  let wake!: () => void;
  const stopped = new Promise<void>(resolve => { wake = resolve; });
  process.once("SIGINT", wake); process.once("SIGTERM", wake);
  try {
    const service = await startDeviceRuntimeService(config!, socket, daemon);
    try {
      console.log(JSON.stringify({ status: "listening", socket: service.socket, pid: process.pid }));
      await Promise.race([stopped, service.failure]);
    } finally { await service.close(); }
  } catch (error) {
    console.error(JSON.stringify({ error: error instanceof RuntimeConflict ? error.code : "device_runtime_startup_failed" }));
    process.exitCode = 2;
  } finally { process.off("SIGINT", wake); process.off("SIGTERM", wake); }
} else {
let owned: ReturnType<typeof openDeviceRuntime> | undefined;
try {
  owned = openDeviceRuntime(config!);
  if (daemon) owned.startDaemon();
  await serveRuntimeControl(owned.control, owned, { keep_alive: daemon });
} catch (error) {
  console.error(JSON.stringify({ error: error instanceof RuntimeConflict ? error.code : "device_runtime_startup_failed" }));
  process.exitCode = 2;
} finally { await owned?.close(); }

}
