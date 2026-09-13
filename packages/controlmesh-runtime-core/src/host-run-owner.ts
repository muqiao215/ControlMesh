import { join } from "node:path";
import type { HostRunTransfer } from "./local-task-runtime";

/** Private stdin carries the transfer, never command text or environment in argv. */
export function dispatchHostOwner(config: string, transfer: HostRunTransfer): void {
  const child = Bun.spawn([process.execPath, join(import.meta.dir, "../scripts/host-run-owner.ts")], {
    detached: true, stdin: "pipe", stdout: "ignore", stderr: "ignore",
  });
  child.stdin.write(JSON.stringify({ config, transfer })); child.stdin.end();
  child.unref();
}
