import { isAbsolute } from "node:path";
import { processIdentity, stopOwnAnchor } from "./process-group";

// Private IPC child of ProcessSupervisor. It stays alive after the provider exits
// so its controller always has a live, verifiable process-group leader to stop.
if (processIdentity(process.pid).group !== process.pid || !process.send) process.exit(64);
let started = false;
let authorizedUntil = performance.now() + 5_000;
let deadline = authorizedUntil;
const timer = setInterval(() => {
  if (performance.now() >= authorizedUntil || performance.now() >= deadline) stopOwnAnchor();
}, 25);
process.on("SIGTERM", () => { /* remain a verifiable anchor during the grace period */ });
process.on("disconnect", () => stopOwnAnchor());
process.on("message", (input: unknown) => {
  if (!input || typeof input !== "object") return;
  const message = input as Record<string, unknown>;
  if (message.type === "renew" && started) {
    authorizedUntil = performance.now() + 1_000;
    return;
  }
  if (message.type !== "start" || started) return;
  started = true;
  const command = message.command as string[];
  const cwd = message.cwd as string;
  const env = message.env as Record<string, string>;
  const timeout = message.timeout_ms as number;
  if (!Array.isArray(command) || !command.length || !command.every(x => typeof x === "string" && !x.includes("\0")) || !isAbsolute(command[0]) || !isAbsolute(cwd) || !Number.isSafeInteger(timeout) || timeout < 1 || timeout > 86_400_000) {
    process.send!({ type: "spawn_failed" });
    return;
  }
  authorizedUntil = performance.now() + 1_000;
  deadline = performance.now() + timeout;
  try {
    const child = Bun.spawn(command, { cwd, env, stdin: "ignore", stdout: "inherit", stderr: "inherit" });
    process.send!({ type: "started", pid: child.pid });
    child.exited.then(code => { process.send?.({ type: "exited", code }); });
  } catch {
    process.send!({ type: "spawn_failed" });
  }
});
process.send({ type: "ready" });
// The interval deliberately stays referenced until the controller stops this group.
void timer;
