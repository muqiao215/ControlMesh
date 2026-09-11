import { isAbsolute, join } from "node:path";
import { processIdentity, signalAnchoredGroup, type ProcessIdentity } from "./process-group";
import { requireThat } from "./value";
import { elapsedMs } from "./elapsed-clock";

export interface ProcessSpec {
  command: string[];
  cwd: string;
  env: Record<string, string>;
  stdin_text?: string;
  timeout_ms: number;
  max_output_bytes?: number;
}
export interface ProcessOutcome {
  reason: "exited" | "deadline" | "cancelled" | "authority_lost" | "output_limit" | "provider_abort" | "spawn_failed" | "anchor_failed";
  exit_code: number | null;
  stdout: string;
  stderr: string;
  duration_ms: number;
}
export interface ProcessAdmission {
  // Supplied by the trusted worker. It must recheck current lease, grant and workspace binding.
  assertCurrent: () => void;
  remainingMs?: () => number;
  signal?: AbortSignal;
  abortOnStderrLine?: (line: string) => boolean;
}

export class ProcessSupervisor {
  async run(spec: ProcessSpec, admission: ProcessAdmission): Promise<ProcessOutcome> {
    requireThat(process.platform === "linux", "process_supervision_platform_unverified");
    requireThat(spec.command.length > 0 && isAbsolute(spec.command[0]) && isAbsolute(spec.cwd), "absolute_process_paths_required");
    requireThat(Number.isSafeInteger(spec.timeout_ms) && spec.timeout_ms > 0 && spec.timeout_ms <= 86_400_000, "invalid_process_deadline");
    requireThat(spec.stdin_text === undefined || (typeof spec.stdin_text === "string" && Buffer.byteLength(spec.stdin_text) <= 65_536), "invalid_process_input");
    const cap = spec.max_output_bytes ?? 4 * 1024 * 1024;
    requireThat(Number.isSafeInteger(cap) && cap > 0 && cap <= 16 * 1024 * 1024, "invalid_output_limit");
    const authorize = () => {
      const checkedAt = elapsedMs();
      const result: unknown = admission.assertCurrent();
      if (result !== undefined) {
        void Promise.resolve(result).catch(() => {});
        requireThat(false, "admission_must_be_synchronous");
      }
      if (!admission.remainingMs) return undefined;
      const remaining = admission.remainingMs();
      requireThat(typeof remaining === "number" && Number.isFinite(remaining) && remaining > 0 && remaining <= 86_400_000, "invalid_authority_deadline");
      return checkedAt + remaining;
    };
    authorize();
    const started = performance.now();
    if (admission.signal?.aborted) return { reason: "cancelled", exit_code: null, stdout: "", stderr: "", duration_ms: 0 };
    let identity: ProcessIdentity | undefined;
    let reason: ProcessOutcome["reason"] | undefined;
    let code: number | null = null;
    let stopping = false;
    let grace: ReturnType<typeof setTimeout> | undefined;
    const stop = (why: ProcessOutcome["reason"]) => {
      if (stopping) {
        if (reason === "exited" && why !== "exited") reason = why;
        return;
      }
      stopping = true;
      reason = why;
      if (identity) {
        try { signalAnchoredGroup(identity, "SIGTERM"); } catch { child.kill("SIGKILL"); }
        grace = setTimeout(() => {
          try { signalAnchoredGroup(identity!, "SIGKILL"); } catch { if (child.exitCode === null) child.kill("SIGKILL"); }
        }, 100);
      } else { child.kill("SIGKILL"); }
    };
    const child = Bun.spawn([process.execPath, join(import.meta.dir, "process-anchor.ts")], {
      detached: true, stdin: "ignore", stdout: "pipe", stderr: "pipe",
      ipc: (message: unknown) => {
        if (!message || typeof message !== "object") return;
        const event = message as Record<string, unknown>;
        if (event.type === "ready") {
          try {
            const authorityDeadline = authorize();
            requireThat(!stopping && !admission.signal?.aborted, "execution_cancelled_before_start");
            identity = processIdentity(child.pid);
            requireThat(identity.group === child.pid && identity.session === child.pid, "anchor_not_detached");
            child.send({ type: "start", ...spec, authority_deadline_ms: authorityDeadline });
          } catch { stop("authority_lost"); }
        } else if (event.type === "exited") {
          code = typeof event.code === "number" ? event.code : null;
          stop("exited");
        } else if (event.type === "spawn_failed") { stop("spawn_failed"); }
      },
    });
    const controller = setInterval(() => {
      try { const authorityDeadline = authorize(); if (!stopping) child.send({ type: "renew", authority_deadline_ms: authorityDeadline }); }
      catch { stop("authority_lost"); }
    }, 100);
    const deadline = setTimeout(() => stop("deadline"), spec.timeout_ms);
    const abort = () => stop("cancelled");
    admission.signal?.addEventListener("abort", abort, { once: true });
    const readers: ReadableStreamDefaultReader<Uint8Array>[] = [];
    let observedBytes = 0;
    const read = async (stream: ReadableStream<Uint8Array>, stderr: boolean) => {
      const reader = stream.getReader();
      readers.push(reader);
      let text = "";
      let line = "";
      const decoder = new TextDecoder();
      try {
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          const remaining = cap - observedBytes;
          observedBytes += value.byteLength;
          const chunk = decoder.decode(value.subarray(0, Math.max(0, remaining)), { stream: true });
          text += chunk;
          if (observedBytes > cap) stop("output_limit");
          if (stderr && admission.abortOnStderrLine) {
            line += chunk;
            const lines = line.split("\n");
            line = lines.pop()!;
            for (const completed of lines) if (admission.abortOnStderrLine(completed)) stop("provider_abort");
          }
        }
        text += decoder.decode();
        if (stderr && line && admission.abortOnStderrLine?.(line)) stop("provider_abort");
      } catch { if (!stopping) stop("anchor_failed"); }
      return text;
    };
    const stdout = read(child.stdout, false);
    const stderr = read(child.stderr, true);
    try {
      await child.exited;
      // An escaped child holding a pipe cannot keep the coordinator waiting forever.
      const drainTimeout = setTimeout(() => { for (const reader of readers) void reader.cancel().catch(() => {}); }, 250);
      const output = await Promise.all([stdout, stderr]);
      clearTimeout(drainTimeout);
      return { reason: reason ?? "anchor_failed", exit_code: code, stdout: output[0], stderr: output[1], duration_ms: Math.round(performance.now() - started) };
    } finally {
      clearInterval(controller);
      clearTimeout(deadline);
      if (grace) clearTimeout(grace);
      admission.signal?.removeEventListener("abort", abort);
      if (child.exitCode === null) stop("anchor_failed");
    }
  }
}
