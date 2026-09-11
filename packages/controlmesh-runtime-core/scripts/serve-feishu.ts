import { openLocalRuntime } from "../src/local-runtime-config";
import { requireThat, RuntimeConflict } from "../src/value";

let owned: ReturnType<typeof openLocalRuntime> | undefined;
try {
  requireThat(process.argv.length === 3, "usage_serve_feishu_private_config_required");
  owned = openLocalRuntime(process.argv[2]); requireThat(owned.inbound, "feishu_inbound_not_configured");
  const listener = owned.inbound.start();
  console.log(JSON.stringify({ status: "listening", ...listener }));
  let stop!: () => void;
  try { await new Promise<void>(resolve => { stop = resolve; process.once("SIGTERM", stop); process.once("SIGINT", stop); }); }
  finally { process.off("SIGTERM", stop); process.off("SIGINT", stop); }
} catch (error) {
  console.error(JSON.stringify({ error: error instanceof RuntimeConflict ? error.code : "feishu_service_failed" })); process.exitCode = 2;
} finally { await owned?.close(); }
