import { createConnection, createServer, type Socket } from "node:net";
import { chmodSync, closeSync, constants, fstatSync, lstatSync, openSync, realpathSync, unlinkSync } from "node:fs";
import { dirname, isAbsolute } from "node:path";
import type { RuntimeControl } from "./device-runtime-control";
import { digest, object, requireThat, RuntimeConflict } from "./value";

const MAX_REQUEST = 65_536, MAX_RESPONSE = 8 * 1024 * 1024;
const identity = (path: string) => { const s = lstatSync(path, { bigint: true }); return digest([String(s.dev), String(s.ino)]); };
function directory(path: string) {
  requireThat(process.platform === "linux" && isAbsolute(path) && Buffer.byteLength(path) < 104, "local_socket_path_invalid");
  const parent = dirname(path), stat = lstatSync(parent);
  requireThat(realpathSync(parent) === parent && stat.isDirectory() && stat.uid === process.getuid!()
    && (stat.mode & 0o077) === 0, "local_socket_directory_not_private");
  return identity(parent);
}
function socketFile(path: string) {
  const stat = lstatSync(path);
  requireThat(stat.isSocket() && stat.uid === process.getuid!() && (stat.mode & 0o077) === 0, "local_socket_not_private");
  return identity(path);
}

/** An OS-held descriptor lock survives helper exit and is released by the kernel on crash. */
class ListenerLock {
  private fd: number | null;
  private readonly file: string;
  private readonly parent: string;
  private readonly before: string;
  constructor(readonly path: string) {
    this.parent = directory(path); this.file = path + ".lock";
    const fd = openSync(this.file, constants.O_RDWR | constants.O_CREAT | constants.O_NOFOLLOW | constants.O_NONBLOCK, 0o600);
    this.fd = fd;
    try {
      const stat = fstatSync(fd, { bigint: true });
      requireThat(stat.isFile() && stat.nlink === 1n && stat.uid === BigInt(process.getuid!()) && (stat.mode & 0o077n) === 0n, "local_socket_lock_not_private");
      const held = Bun.spawnSync(["/usr/bin/flock", "--nonblock", "--conflict-exit-code", "75", "3"], {
        stdio: ["ignore", "ignore", "ignore", fd], timeout: 2000,
      });
      requireThat(held.exitCode === 0, held.exitCode === 75 ? "local_service_already_running" : "local_socket_lock_unavailable");
      this.before = digest([String(stat.dev), String(stat.ino)]); this.assertCurrent();
    } catch (error) { this.close(); throw error; }
  }
  assertCurrent() {
    requireThat(this.fd !== null && directory(this.path) === this.parent && identity(this.file) === this.before, "local_socket_authority_changed");
  }
  close() { if (this.fd !== null) { closeSync(this.fd); this.fd = null; } }
}

async function removeCrashedSocket(path: string, lock: ListenerLock) {
  let before: string;
  try { before = socketFile(path); } catch (error) { if ((error as NodeJS.ErrnoException).code === "ENOENT") return; throw error; }
  const refused = await new Promise<boolean>((resolve, reject) => {
    const probe = createConnection(path);
    probe.setTimeout(1000, () => { probe.destroy(); reject(new RuntimeConflict("local_socket_owner_unknown")); });
    probe.once("connect", () => { probe.destroy(); resolve(false); });
    // Bun 1.3.11 reports ENOENT for a SIGKILL-orphaned Unix socket whose inode still exists.
    // Both refusals need the held lock and unchanged inode below; timeout/permission errors do not qualify.
    probe.once("error", error => ["ECONNREFUSED", "ENOENT"].includes(String((error as NodeJS.ErrnoException).code))
      ? resolve(true) : reject(new RuntimeConflict("local_socket_owner_unknown")));
  });
  requireThat(refused, "local_service_already_running"); lock.assertCurrent();
  requireThat(socketFile(path) === before, "local_socket_authority_changed"); unlinkSync(path);
}

/** Private local transport. Disconnect abandons a reply, never task execution or request identity. */
export async function listenRuntimeControl(path: string, control: RuntimeControl, stopOwned: () => Promise<void> = async () => {}) {
  const lock = new ListenerLock(path), sockets = new Set<Socket>(), pending = new Set<Promise<void>>();
  let stopping = false, closing: Promise<void> | undefined, bound: string | undefined;
  const current = () => { lock.assertCurrent(); requireThat(!stopping && bound === socketFile(path), "local_socket_authority_changed"); };
  const server = createServer(socket => {
    if (stopping || sockets.size >= 32) { socket.destroy(); return; }
    try { current(); } catch { socket.destroy(); return; }
    sockets.add(socket); let buffered = Buffer.alloc(0), inFlight = 0;
    const send = (response: Record<string, unknown>) => {
      if (socket.destroyed || stopping) return;
      let line = JSON.stringify(response);
      if (Buffer.byteLength(line) > MAX_RESPONSE) line = JSON.stringify({ id: response.id ?? null, ok: false, error: "local_response_too_large" });
      if (socket.writableLength + Buffer.byteLength(line) > MAX_RESPONSE * 2) { socket.destroy(); return; }
      socket.write(line + "\n");
    };
    const reject = (code: string) => { send({ id: null, ok: false, error: code }); socket.end(); socket.pause(); };
    socket.setTimeout(30_000, () => { if (!inFlight) socket.destroy(); });
    socket.on("error", () => {}); socket.once("close", () => sockets.delete(socket));
    socket.on("data", chunk => {
      try {
        requireThat(Buffer.isBuffer(chunk), "invalid_local_transport_data");
        current(); requireThat(chunk.length <= 1024 * 1024, "local_control_backpressure");
        buffered = Buffer.concat([buffered, chunk]); let newline: number;
        while ((newline = buffered.indexOf(10)) >= 0) {
          requireThat(newline <= MAX_REQUEST && pending.size < 128 && inFlight < 8, "local_control_backpressure");
          const line = buffered.subarray(0, newline); buffered = buffered.subarray(newline + 1);
          if (!line.length) continue;
          let request: unknown;
          try { request = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(line)); }
          catch { reject("invalid_local_request"); return; }
          inFlight++;
          const job = Promise.resolve().then(() => { current(); return control.handle(request); }).then(send,
            error => send({ id: object(request) && typeof request.id === "string" ? request.id : null, ok: false,
              error: error instanceof RuntimeConflict ? error.code : "local_runtime_error" }))
            .finally(() => { inFlight--; pending.delete(job); });
          pending.add(job);
        }
        requireThat(buffered.length <= MAX_REQUEST, "local_request_too_large");
      } catch (error) { reject(error instanceof RuntimeConflict ? error.code : "local_socket_authority_changed"); }
    });
  });
  try {
    await removeCrashedSocket(path, lock); lock.assertCurrent();
    await new Promise<void>((resolve, reject) => { server.once("error", reject); server.listen(path, () => { server.off("error", reject); resolve(); }); });
    chmodSync(path, 0o600); bound = socketFile(path);
  } catch (error) { if (server.listening) server.close(); lock.close(); throw error; }
  return {
    path, assertCurrent: current,
    close: () => closing ??= (async () => {
      stopping = true;
      const closed = new Promise<void>(resolve => server.close(() => resolve()));
      for (const socket of sockets) socket.destroy();
      try {
        await stopOwned(); await Promise.allSettled([...pending]); await closed;
        // Bun leaves a Unix pathname behind on close. Remove only this listener's inode,
        // while still holding its OS lock; a replaced path belongs to someone else.
        try { lock.assertCurrent(); if (bound === socketFile(path)) unlinkSync(path); }
        catch (error) { if (!(error instanceof RuntimeConflict) && (error as NodeJS.ErrnoException).code !== "ENOENT") throw error; }
      } finally { lock.close(); }
    })(),
  };
}

/** One explicit command, one connection, no retry after an uncertain response. */
export async function requestRuntimeControl(path: string, request: Record<string, unknown>, timeoutMs = 30_000): Promise<Record<string, unknown>> {
  let before: string;
  try { directory(path); before = socketFile(path); }
  catch (error) { if ((error as NodeJS.ErrnoException).code === "ENOENT") throw new RuntimeConflict("local_control_unavailable"); throw error; }
  requireThat(Number.isSafeInteger(timeoutMs) && timeoutMs >= 1 && timeoutMs <= 300_000, "invalid_local_control_timeout");
  const input = JSON.stringify(request); requireThat(Buffer.byteLength(input) <= MAX_REQUEST, "local_request_too_large");
  return new Promise((resolve, reject) => {
    const socket = createConnection(path); let sent = false, settled = false, buffered = Buffer.alloc(0);
    const finish = (error?: unknown, result?: Record<string, unknown>) => {
      if (settled) return; settled = true; clearTimeout(timer); socket.destroy(); if (error) reject(error); else resolve(result!);
    };
    const unknown = () => new RuntimeConflict(sent ? "local_control_response_unknown" : "local_control_unavailable");
    const timer = setTimeout(() => finish(unknown()), timeoutMs);
    socket.once("connect", () => {
      try { directory(path); requireThat(socketFile(path) === before, "local_socket_authority_changed"); sent = true; socket.write(input + "\n"); }
      catch (error) { finish(error); }
    });
    socket.on("data", chunk => {
      try {
        requireThat(Buffer.isBuffer(chunk), "invalid_local_transport_data");
        buffered = Buffer.concat([buffered, chunk]); requireThat(buffered.length <= MAX_RESPONSE + 1, "local_response_too_large");
        const newline = buffered.indexOf(10); if (newline < 0) return;
        const result: unknown = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(buffered.subarray(0, newline)));
        requireThat(object(result) && result.id === request.id && typeof result.ok === "boolean", "local_control_response_invalid"); finish(undefined, result);
      } catch (error) { finish(error); }
    });
    socket.once("error", () => finish(unknown())); socket.once("close", () => { if (!settled) finish(unknown()); });
  });
}
