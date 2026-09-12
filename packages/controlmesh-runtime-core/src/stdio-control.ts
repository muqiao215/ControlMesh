import { requireThat } from "./value";
import type { RuntimeControl } from "./device-runtime-control";

/** Shared bounded stdin/stdout transport; shutdown interrupts only work owned by this runtime. */
export async function serveRuntimeControl(control: RuntimeControl, owned: { stop(): Promise<void>; close(): Promise<void> }, options: { keep_alive?: boolean } = {}): Promise<void> {
  const pending = new Set<Promise<void>>();
  const output = (value: unknown) => new Promise<void>((resolve, reject) => {
    process.stdout.write(JSON.stringify(value) + "\n", error => error ? reject(error) : resolve());
  });
  const decoder = new TextDecoder("utf-8", { fatal: true });
  let buffer = "", failed: unknown, stopping = false;
  const dispatch = (line: string) => {
    requireThat(Buffer.byteLength(line) <= 65_536 && pending.size < 128, "local_control_backpressure");
    if (!line.trim()) return;
    let request: unknown;
    try { request = JSON.parse(line); } catch { request = null; }
    const reply = control.handle(request).then(output).finally(() => pending.delete(reply));
    void reply.catch(error => { failed = error; process.stdin.destroy(); });
    pending.add(reply);
  };
  let wake!: () => void;
  const interruptedSignal = new Promise<void>(resolve => { wake = resolve; });
  const interrupted = () => { stopping = true; void owned.stop().catch(error => { failed = error; }).finally(() => { process.stdin.destroy(); wake(); }); };
  process.once("SIGTERM", interrupted); process.once("SIGINT", interrupted);
  try {
    try {
      for await (const chunk of process.stdin) {
        if (stopping) break;
        requireThat(chunk.byteLength <= 1024 * 1024, "local_control_backpressure");
        buffer += decoder.decode(chunk, { stream: true });
        let newline: number;
        while ((newline = buffer.indexOf("\n")) >= 0) { const line = buffer.slice(0, newline); buffer = buffer.slice(newline + 1); dispatch(line); }
        requireThat(Buffer.byteLength(buffer) <= 65_536, "local_request_too_large");
      }
    } catch (error) {
      // Destroying our own input on SIGTERM/SIGINT is expected; other stream failures remain errors.
      if (!stopping || !["ERR_STREAM_PREMATURE_CLOSE", "ABORT_ERR"].includes(String((error as NodeJS.ErrnoException)?.code))) throw error;
    }
    if (!stopping) { buffer += decoder.decode(); if (buffer.trim()) dispatch(buffer); }
    await Promise.all(pending); if (failed) throw failed;
    if (options.keep_alive && !stopping) await interruptedSignal;
    if (failed) throw failed;
  } finally { process.off("SIGTERM", interrupted); process.off("SIGINT", interrupted); }
}
