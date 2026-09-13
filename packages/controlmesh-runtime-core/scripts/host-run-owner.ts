import { openLocalRuntime } from "../src/local-runtime-config";
import { object, requireThat } from "../src/value";
import type { HostRunTransfer } from "../src/local-task-runtime";

let owned: ReturnType<typeof openLocalRuntime> | undefined;
try {
  const input = await Bun.stdin.text();
  requireThat(Buffer.byteLength(input) <= 16384, "host_owner_input_too_large");
  const request: unknown = JSON.parse(input);
  requireThat(object(request) && typeof request.config === "string" && object(request.transfer)
    , "invalid_host_owner_request");
  const transfer = request.transfer;
  requireThat(["run_id", "previous_owner", "binding_digest"].every(key => typeof transfer[key] === "string"), "invalid_host_owner_request");
  owned = openLocalRuntime(request.config, { host_worker: true });
  await owned.runtime.acceptHostRun(request.transfer as unknown as HostRunTransfer);
} catch { process.exitCode = 2; }
finally { await owned?.close(); }
