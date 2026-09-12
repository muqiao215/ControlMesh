import { openLocalRuntime } from "../src/local-runtime-config";
import { LocalRuntimeControl } from "../src/local-runtime-control";
import { RuntimeConflict } from "../src/value";
import { serveRuntimeControl } from "../src/stdio-control";

if (process.argv.length !== 3) {
  console.error("Usage: bun scripts/local-runtime.ts /absolute/private-config.json\nIsolated candidate TypeScript coordinator; JSON-lines control on stdin/stdout.");
  process.exit(2);
}

let owned: ReturnType<typeof openLocalRuntime> | undefined;
try {
  owned = openLocalRuntime(process.argv[2]);
  const control = new LocalRuntimeControl(owned.runtime, owned.deliveries, owned.submissionIdentity, owned.inbound, owned.specmesh, owned.recovery, owned.history);
  await serveRuntimeControl(control, owned);
} catch (error) {
  console.error(JSON.stringify({ error: error instanceof RuntimeConflict ? error.code : "local_runtime_startup_failed" }));
  process.exitCode = 2;
} finally { await owned?.close(); }
