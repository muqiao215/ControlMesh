import { isAbsolute } from "node:path";
import { processIdentity, stopOwnAnchor } from "./process-group";
import { elapsedMs } from "./elapsed-clock";

// Private IPC child of ProcessSupervisor. It stays alive after the provider exits
// so its controller always has a live, verifiable process-group leader to stop.
if (processIdentity(process.pid).group !== process.pid || !process.send) process.exit(64);
let started = false;
let authorizedUntil = elapsedMs() + 5_000;
let deadline = authorizedUntil;
let leaseDeadline = Infinity;
function updateLease(message: Record<string, unknown>): void {
  const value = message.authority_deadline_ms;
  if (value === undefined && leaseDeadline === Infinity) return;
  if (typeof value !== "number" || !Number.isFinite(value) || value <= elapsedMs()) stopOwnAnchor();
  leaseDeadline = value as number;
}
const timer = setInterval(() => {
  try { if (elapsedMs() >= authorizedUntil || elapsedMs() >= deadline || elapsedMs() >= leaseDeadline) stopOwnAnchor(); }
  catch { stopOwnAnchor(); }
}, 25);
process.on("SIGTERM", () => { /* remain a verifiable anchor during the grace period */ });
process.on("disconnect", () => stopOwnAnchor());
process.on("message", (input: unknown) => {
  if (!input || typeof input !== "object") return;
  const message = input as Record<string, unknown>;
  if (message.type === "renew" && started) {
    // An old queued IPC renewal must not revive an anchor after suspend or controller loss.
    if (elapsedMs() >= authorizedUntil || elapsedMs() >= deadline || elapsedMs() >= leaseDeadline) stopOwnAnchor();
    updateLease(message);
    authorizedUntil = elapsedMs() + 1_000;
    return;
  }
  if (message.type !== "start" || started) return;
  started = true;
  const command = message.command as string[];
  const cwd = message.cwd as string;
  const env = message.env as Record<string, string>;
  const timeout = message.timeout_ms as number;
  const stdin = message.stdin_text;
  if (!Array.isArray(command) || !command.length || !command.every(x => typeof x === "string" && !x.includes("\0")) || !isAbsolute(command[0]) || !isAbsolute(cwd) || !Number.isSafeInteger(timeout) || timeout < 1 || timeout > 86_400_000 || (stdin !== undefined && (typeof stdin !== "string" || Buffer.byteLength(stdin) > 65_536))) {
    process.send!({ type: "spawn_failed" });
    return;
  }
  if (elapsedMs() >= authorizedUntil) stopOwnAnchor();
  updateLease(message);
  authorizedUntil = elapsedMs() + 1_000;
  deadline = elapsedMs() + timeout;
  try {
    const child = Bun.spawn(command, { cwd, env, stdin: "pipe", stdout: "inherit", stderr: "inherit" });
    if (typeof stdin === "string") child.stdin.write(stdin);
    child.stdin.end();
    process.send!({ type: "started", pid: child.pid });
    child.exited.then(code => { process.send?.({ type: "exited", code }); });
  } catch {
    process.send!({ type: "spawn_failed" });
  }
});
process.send({ type: "ready" });
// The interval deliberately stays referenced until the controller stops this group.
void timer;
