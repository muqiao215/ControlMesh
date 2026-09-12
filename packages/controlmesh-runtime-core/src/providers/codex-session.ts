import { createHash } from "node:crypto";
import { closeSync, constants, fstatSync, lstatSync, openSync, readSync, realpathSync, statSync, type BigIntStats } from "node:fs";
import { basename, isAbsolute } from "node:path";
import { canonical, digest, identifier, object, requireThat } from "../value";

export interface CodexSessionRef {
  schema_version: "agent.native_session.v2";
  provider: "codex";
  device_id: string; store_id: string; session_id: string;
  directory: string; project_id: string; revision: string; model: string; title: string;
}
export interface CodexNativeBaseline {
  schema_version: "codex.native_baseline.v1";
  reference: CodexSessionRef;
  byte_length: number;
  record_count: number;
}
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;
const identity = (stat: BigIntStats) => [stat.dev, stat.ino, stat.size, stat.mtimeNs, stat.ctimeNs].map(String).join(":");
const revision = (store: string, bytes: Uint8Array) => createHash("sha256").update(canonical(["codex-rollout-content-v1", store]) + "\n").update(bytes).digest("hex");
interface Turn { id: string; model: string; prompt: string | null; output: string | null; completed: boolean }

/** Strict execution evidence; tolerant UI indexing must not authorize a native resume. */
export class CodexSessionStore {
  constructor(readonly path: string, readonly deviceId: string) { identifier(deviceId); }
  snapshot(sessionId: string) {
    requireThat(uuid.test(sessionId), "invalid_native_session_id");
    requireThat(isAbsolute(this.path) && realpathSync(this.path) === this.path, "native_store_path_must_be_canonical");
    requireThat(basename(this.path).startsWith("rollout-") && basename(this.path).endsWith(`-${sessionId}.jsonl`), "native_session_path_mismatch");
    const before = lstatSync(this.path, { bigint: true });
    requireThat(before.isFile() && before.size > 0n && before.size <= 32n * 1024n * 1024n, "native_session_size_invalid");
    const fd = openSync(this.path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
    let bytes: Buffer;
    try {
      requireThat(identity(fstatSync(fd, { bigint: true })) === identity(before), "native_store_changed");
      const buffer = Buffer.alloc(Number(before.size) + 1); let count = 0;
      while (count < buffer.length) { const n = readSync(fd, buffer, count, buffer.length - count, null); if (!n) break; count += n; }
      requireThat(count === Number(before.size) && identity(fstatSync(fd, { bigint: true })) === identity(before), "native_store_changed");
      bytes = buffer.subarray(0, count);
    } finally { closeSync(fd); }
    requireThat(identity(lstatSync(this.path, { bigint: true })) === identity(before) && realpathSync(this.path) === this.path, "native_store_changed");
    requireThat(bytes.at(-1) === 10, "native_transcript_incomplete");
    const lines = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(bytes).split("\n").slice(0, -1);
    requireThat(lines.length <= 100000, "native_session_too_large");
    const records = lines.map(line => { const row: unknown = JSON.parse(line); requireThat(object(row) && typeof row.type === "string" && object(row.payload), "unsupported_native_schema"); return row; });
    const meta = records[0]?.payload;
    requireThat(records[0]?.type === "session_meta" && object(meta) && meta.id === sessionId
      && (meta.session_id === undefined || meta.session_id === sessionId), "native_session_mismatch");
    requireThat(typeof meta.cwd === "string" && isAbsolute(meta.cwd) && statSync(meta.cwd).isDirectory(), "native_directory_unavailable");
    const directory = realpathSync(meta.cwd); let model = "";
    for (const [index, row] of records.entries()) {
      const payload = row.payload as Record<string, unknown>;
      requireThat(index === 0 || row.type !== "session_meta", "native_session_mismatch");
      requireThat(payload.thread_id === undefined || payload.thread_id === sessionId, "native_session_mismatch");
      if (row.type === "turn_context") {
        requireThat(typeof payload.cwd === "string" && realpathSync(payload.cwd) === directory, "native_directory_changed");
        requireThat(typeof payload.model === "string" && payload.model.length > 0, "native_model_missing"); model = payload.model;
      }
    }
    requireThat(model.length > 0, "native_model_missing");
    const storeId = digest(["codex-rollout-store-v1", this.deviceId, this.path, String(before.dev), String(before.ino)]);
    const reference: CodexSessionRef = { schema_version: "agent.native_session.v2", provider: "codex", device_id: this.deviceId,
      store_id: storeId, session_id: sessionId, directory, project_id: digest(["codex-project-v1", directory]), revision: revision(storeId, bytes), model, title: "" };
    return { reference, bytes, records };
  }
  read(sessionId: string): CodexSessionRef { return this.snapshot(sessionId).reference; }
  validate(ref: CodexSessionRef): CodexSessionRef {
    requireThat(ref.schema_version === "agent.native_session.v2" && ref.provider === "codex", "unsupported_native_reference");
    requireThat(ref.device_id === this.deviceId, "native_device_mismatch");
    const current = this.read(ref.session_id);
    requireThat(current.store_id === ref.store_id && current.directory === ref.directory && current.project_id === ref.project_id, "native_identity_changed");
    requireThat(current.revision === ref.revision && current.model === ref.model, "native_revision_changed"); return current;
  }
  baseline(ref: CodexSessionRef): CodexNativeBaseline {
    const current = this.snapshot(ref.session_id);
    requireThat(digest(current.reference) === digest(ref), "native_reference_changed");
    this.turns(current.records);
    return { schema_version: "codex.native_baseline.v1", reference: ref, byte_length: current.bytes.length, record_count: current.records.length };
  }
  verifyTurn(sessionId: string, before: CodexNativeBaseline | null, prompt: string, output: string, model: string) {
    const current = this.snapshot(sessionId); let offset = 0;
    const previousTurns = new Set<string>();
    if (before) {
      requireThat(before.schema_version === "codex.native_baseline.v1" && Number.isSafeInteger(before.byte_length) && before.byte_length > 0
        && Number.isSafeInteger(before.record_count) && before.record_count > 0, "invalid_native_baseline");
      const old = before.reference, next = current.reference;
      requireThat(old.provider === "codex" && old.schema_version === "agent.native_session.v2" && old.session_id === next.session_id
        && old.store_id === next.store_id && old.directory === next.directory && old.device_id === next.device_id && old.project_id === next.project_id, "native_identity_changed");
      const prefix = current.bytes.subarray(0, before.byte_length);
      requireThat(current.bytes.length > before.byte_length && prefix.at(-1) === 10 && revision(old.store_id, prefix) === old.revision, "native_prior_content_changed");
      requireThat(prefix.filter(byte => byte === 10).length === before.record_count, "invalid_native_baseline");
      for (const turn of this.turns(current.records.slice(0, before.record_count))) previousTurns.add(turn.id);
      offset = before.record_count;
    }
    const turns = this.turns(current.records.slice(offset));
    requireThat(turns.length === 1 && !previousTurns.has(turns[0].id), "native_concurrent_turn_or_missing_lineage");
    const turn = turns[0];
    requireThat(turn.model === model && current.reference.model === model, "native_model_mismatch");
    requireThat(turn.prompt === prompt && turn.output === output, "native_turn_content_mismatch");
    return { reference: current.reference, turn_id: turn.id, prompt_sha256: digest(prompt), output_sha256: digest(output) };
  }
  private turns(records: Record<string, unknown>[]): Turn[] {
    const turns: Turn[] = [], ids = new Set<string>(); let active: Turn | undefined;
    for (const row of records) {
      const p = row.payload as Record<string, unknown>;
      if (row.type === "event_msg" && p.type === "task_started") {
        requireThat(!active && typeof p.turn_id === "string" && p.turn_id.length > 0 && !ids.has(p.turn_id), "native_concurrent_turn_or_missing_lineage");
        ids.add(p.turn_id); active = { id: p.turn_id, model: "", prompt: null, output: null, completed: false };
      } else if (row.type === "turn_context") {
        requireThat(active && p.turn_id === active.id && typeof p.model === "string" && (!active.model || active.model === p.model), "native_turn_context_mismatch");
        active.model = p.model;
      } else if (row.type === "event_msg" && p.type === "user_message") {
        requireThat(active && active.prompt === null && typeof p.message === "string", "native_concurrent_turn_or_missing_lineage"); active.prompt = p.message;
      } else if (row.type === "event_msg" && p.type === "agent_message" && p.phase === "final") {
        requireThat(active && active.output === null && typeof p.message === "string", "native_turn_content_mismatch"); active.output = p.message;
      } else if (row.type === "event_msg" && p.type === "task_complete") {
        requireThat(active && p.turn_id === active.id && active.prompt !== null && active.output !== null && active.model
          && p.last_agent_message === active.output, "native_turn_not_completed");
        active.completed = true; turns.push(active); active = undefined;
      } else if (row.type === "event_msg" && ["turn_aborted", "error", "task_failed"].includes(String(p.type))) {
        requireThat(false, "native_turn_not_completed");
      }
    }
    requireThat(!active && turns.length > 0, "native_turn_not_completed"); return turns;
  }
}
