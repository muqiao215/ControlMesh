import { createHash } from "node:crypto";
import { closeSync, constants, fstatSync, lstatSync, openSync, readSync, realpathSync, statSync, type BigIntStats } from "node:fs";
import { basename, isAbsolute } from "node:path";
import { canonical, digest, identifier, object, requireThat } from "../value";
import type { NativeSessionRef } from "./native-session";
import { inspectClaudeChain, type ClaudeTurnEvidence } from "./claude-turn";

export type ClaudeSessionRef = NativeSessionRef<"claude">;
export interface ClaudeNativeBaseline {
  schema_version: "claude.native_baseline.v1";
  reference: ClaudeSessionRef;
  byte_length: number;
  record_count: number;
  tip_uuid: string;
}
const MAX_BYTES = 32 * 1024 * 1024;
const sessionPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const identity = (s: BigIntStats) => [s.dev, s.ino, s.size, s.mtimeNs, s.ctimeNs].map(String).join(":");

export function claudeContentRevision(storeId: string, bytes: Uint8Array): string {
  return createHash("sha256").update(canonical(["claude-jsonl-content-v2", storeId]) + "\n").update(bytes).digest("hex");
}

/** Strict executable-context inspection. The UI's tolerant parser must not authorize resume. */
export class ClaudeSessionStore {
  constructor(readonly path: string, readonly deviceId: string) { identifier(deviceId); }

  read(sessionId: string): ClaudeSessionRef { return this.snapshot(sessionId).reference; }

  snapshot(sessionId: string): { reference: ClaudeSessionRef; bytes: Buffer; records: Record<string, unknown>[] } {
    requireThat(sessionPattern.test(sessionId), "invalid_native_session_id");
    requireThat(isAbsolute(this.path) && realpathSync(this.path) === this.path, "native_store_path_must_be_canonical");
    requireThat(basename(this.path) === `${sessionId}.jsonl`, "native_session_path_mismatch");
    const before = lstatSync(this.path, { bigint: true });
    requireThat(before.isFile(), "native_store_not_regular");
    requireThat(before.size <= BigInt(MAX_BYTES), "native_session_too_large");
    const fd = openSync(this.path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
    let bytes: Buffer;
    try {
      requireThat(identity(fstatSync(fd, { bigint: true })) === identity(before), "native_store_changed");
      const buffer = Buffer.alloc(Number(before.size) + 1); let count = 0, n: number;
      do { n = readSync(fd, buffer, count, buffer.length - count, null); count += n; } while (n && count < buffer.length);
      requireThat(count === Number(before.size) && identity(fstatSync(fd, { bigint: true })) === identity(before), "native_store_changed");
      bytes = buffer.subarray(0, count);
    } finally { closeSync(fd); }
    requireThat(identity(lstatSync(this.path, { bigint: true })) === identity(before) && realpathSync(this.path) === this.path, "native_store_changed");
    requireThat(bytes.length > 0 && bytes.at(-1) === 10, "native_transcript_incomplete");
    const lines = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(bytes).split("\n").slice(0, -1);
    requireThat(lines.length <= 100_000, "native_session_too_large");
    const records: Record<string, unknown>[] = [];
    let directory: string | undefined, model = "", title = "", messages = 0;
    for (const line of lines) {
      const row: unknown = JSON.parse(line); requireThat(object(row), "unsupported_native_schema");
      requireThat(!("sessionId" in row) || row.sessionId === sessionId, "native_session_mismatch");
      if (row.type === "user" || row.type === "assistant") {
        const message = row.message;
        requireThat(row.sessionId === sessionId && row.isSidechain !== true && object(message) && message.role === row.type, "unsupported_native_lineage");
        requireThat(typeof row.cwd === "string" && isAbsolute(row.cwd) && statSync(row.cwd).isDirectory(), "native_directory_unavailable");
        const current = realpathSync(row.cwd);
        requireThat(directory === undefined || directory === current, "native_directory_changed"); directory = current; messages++;
        if (row.type === "assistant" && typeof message.model === "string" && !message.model.startsWith("<")) model = message.model;
      }
      const value = row.type === "custom-title" ? row.customTitle : row.type === "ai-title" ? row.aiTitle : null;
      if (typeof value === "string") title = Array.from(value).slice(0, 512).join("");
      records.push(row);
    }
    requireThat(messages > 0 && directory, "native_session_missing");
    const storeId = digest(["claude-jsonl-store-v2", this.deviceId, this.path, String(before.dev), String(before.ino)]);
    const revision = claudeContentRevision(storeId, bytes);
    return { reference: { schema_version: "agent.native_session.v2", provider: "claude", device_id: this.deviceId, store_id: storeId,
      session_id: sessionId, directory, project_id: digest(["claude-project-v2", directory]), revision, model, title }, bytes, records };
  }

  validate(ref: ClaudeSessionRef): ClaudeSessionRef {
    requireThat(ref.schema_version === "agent.native_session.v2" && ref.provider === "claude", "unsupported_native_reference");
    requireThat(ref.device_id === this.deviceId, "native_device_mismatch");
    const current = this.read(ref.session_id);
    requireThat(current.store_id === ref.store_id && current.directory === ref.directory && current.project_id === ref.project_id, "native_identity_changed");
    requireThat(current.revision === ref.revision && current.model === ref.model, "native_revision_changed"); return current;
  }

  baseline(ref: ClaudeSessionRef): ClaudeNativeBaseline {
    const current = this.snapshot(ref.session_id);
    requireThat(digest(current.reference) === digest(ref), "native_reference_changed");
    const chain = inspectClaudeChain(current.records, ref.session_id, ref.directory);
    return { schema_version: "claude.native_baseline.v1", reference: current.reference, byte_length: current.bytes.length,
      record_count: current.records.length, tip_uuid: chain.tip_uuid };
  }

  /** Re-read retained native bytes after execution or after a lost observation; never run a model. */
  verifyTurn(sessionId: string, before: ClaudeNativeBaseline | null, prompt: string, output: string, model: string): ClaudeTurnEvidence & { reference: ClaudeSessionRef } {
    const current = this.snapshot(sessionId), { reference, records, bytes } = current;
    let offset = 0;
    if (before) {
      requireThat(before.schema_version === "claude.native_baseline.v1" && Number.isSafeInteger(before.byte_length) && before.byte_length > 0
        && Number.isSafeInteger(before.record_count) && before.record_count > 0, "invalid_native_baseline");
      const old = before.reference;
      requireThat(old.provider === "claude" && old.schema_version === "agent.native_session.v2" && reference.session_id === old.session_id
        && reference.device_id === old.device_id && reference.store_id === old.store_id && reference.directory === old.directory
        && reference.project_id === old.project_id, "native_identity_changed");
      requireThat(bytes.length > before.byte_length && bytes[before.byte_length - 1] === 10
        && claudeContentRevision(reference.store_id, bytes.subarray(0, before.byte_length)) === old.revision, "native_prior_content_changed");
      offset = before.record_count;
      requireThat(offset < records.length && bytes.subarray(0, before.byte_length).filter(byte => byte === 10).length === offset, "invalid_native_baseline");
      requireThat(inspectClaudeChain(records.slice(0, offset), sessionId, reference.directory).tip_uuid === before.tip_uuid, "native_baseline_tip_changed");
    }
    const chain = inspectClaudeChain(records, sessionId, reference.directory, offset);
    requireThat(chain.turns.length === 1, "native_concurrent_turn_or_missing_lineage");
    const turn = chain.turns[0];
    requireThat(!turn.interrupted, "native_turn_not_completed");
    requireThat(turn.models.length > 0 && turn.models.every(value => value === model) && reference.model === model, "native_model_mismatch");
    requireThat(turn.prompt === prompt && turn.evidence.output === output, "native_turn_content_mismatch");
    return { reference, ...turn.evidence };
  }
}
