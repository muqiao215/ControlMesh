import { createHash } from "node:crypto";
import { closeSync, constants, fstatSync, lstatSync, openSync, readSync, realpathSync } from "node:fs";
import { basename, isAbsolute } from "node:path";
import { canonical, digest, identifier, object, requireThat } from "../value";

const uuid = /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/;
const revision = (store: string, bytes: Uint8Array) => createHash("sha256").update(canonical(["gemini-jsonl-v1", store]) + "\n").update(bytes).digest("hex");
export const geminiProjectHash = (workspace: string) => createHash("sha256").update(workspace).digest("hex");
export interface GeminiNativeBaseline {
  schema_version: "gemini.native_baseline.v1"; session_id: string; store_id: string;
  revision: string; byte_length: number; record_count: number;
}
function replay(records: Record<string, unknown>[], session: string, project: string) {
  const messages = new Map<string, Record<string, unknown>>();
  let metadata: Record<string, unknown> = {};
  const message = (row: unknown) => {
    requireThat(object(row) && typeof row.id === "string" && row.id.length > 0 && row.id.length <= 256
      && typeof row.type === "string" && typeof row.timestamp === "string"
      && (typeof row.content === "string" || Array.isArray(row.content)), "gemini_message_invalid");
    messages.set(row.id, row);
  };
  requireThat(records[0]?.sessionId === session && records[0]?.projectHash === project, "gemini_session_identity_changed");
  for (const row of records) {
    if (Object.hasOwn(row, "$rewindTo")) {
      requireThat(typeof row.$rewindTo === "string" && Object.keys(row).length === 1, "gemini_rewind_invalid");
      const ids = [...messages.keys()], index = ids.indexOf(row.$rewindTo);
      for (const id of index < 0 ? ids : ids.slice(index)) messages.delete(id);
    } else if (Object.hasOwn(row, "id")) message(row);
    else if (Object.hasOwn(row, "$set")) {
      requireThat(object(row.$set) && Object.keys(row).length === 1, "gemini_metadata_invalid");
      if (Object.hasOwn(row.$set, "messages")) {
        requireThat(Array.isArray(row.$set.messages) && row.$set.messages.length <= 100000, "gemini_message_limit");
        messages.clear(); for (const item of row.$set.messages) message(item);
      }
      metadata = { ...metadata, ...row.$set };
    } else {
      requireThat(typeof row.sessionId === "string" && typeof row.projectHash === "string", "unsupported_gemini_record");
      metadata = { ...metadata, ...row };
    }
    requireThat(metadata.sessionId === session && metadata.projectHash === project, "gemini_session_identity_changed");
  }
  requireThat(typeof metadata.startTime === "string" && typeof metadata.lastUpdated === "string", "gemini_metadata_invalid");
  const values = [...messages.values()];
  const model = values.filter(item => item.type === "gemini" && typeof item.model === "string").at(-1)?.model;
  return { metadata, messages: values, model: typeof model === "string" ? model : null };
}

/** Gemini CLI 0.59 JSONL reader. A readable transcript alone is not completion evidence. */
export class GeminiSessionStore {
  constructor(readonly path: string, readonly deviceId: string, readonly workspace: string) { identifier(deviceId); }
  snapshot(sessionId: string) {
    requireThat(uuid.test(sessionId), "invalid_native_session_id");
    requireThat(isAbsolute(this.path) && realpathSync(this.path) === this.path
      && isAbsolute(this.workspace) && realpathSync(this.workspace) === this.workspace && lstatSync(this.workspace).isDirectory(), "native_store_path_must_be_canonical");
    requireThat(basename(this.path).startsWith("session-") && basename(this.path).endsWith(`-${sessionId.slice(0, 8)}.jsonl`), "native_session_path_mismatch");
    const before = lstatSync(this.path, { bigint: true });
    const stamp = (s: typeof before) => [s.dev, s.ino, s.size, s.mtimeNs, s.ctimeNs].map(String).join(":");
    requireThat(before.isFile() && before.size > 0n && before.size <= 32n * 1024n * 1024n, "native_session_size_invalid");
    const fd = openSync(this.path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
    let bytes: Buffer;
    try {
      requireThat(stamp(fstatSync(fd, { bigint: true })) === stamp(before), "native_store_changed");
      const buffer = Buffer.alloc(Number(before.size) + 1); let count = 0;
      while (count < buffer.length) { const n = readSync(fd, buffer, count, buffer.length - count, null); if (!n) break; count += n; }
      requireThat(count === Number(before.size) && stamp(fstatSync(fd, { bigint: true })) === stamp(before), "native_store_changed");
      bytes = buffer.subarray(0, count);
    } finally { closeSync(fd); }
    requireThat(realpathSync(this.path) === this.path && stamp(lstatSync(this.path, { bigint: true })) === stamp(before), "native_store_changed");
    requireThat(bytes.at(-1) === 10, "native_transcript_incomplete");
    const lines = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(bytes).split("\n").slice(0, -1);
    requireThat(lines.length <= 100000, "native_session_too_large");
    const records = lines.map(line => { const row: unknown = JSON.parse(line); requireThat(object(row), "unsupported_gemini_record"); return row; });
    const store_id = digest(["gemini-jsonl-store-v1", this.deviceId, this.path, String(before.dev), String(before.ino), this.workspace]);
    return { ...replay(records, sessionId, geminiProjectHash(this.workspace)), bytes, records, store_id, session_id: sessionId, revision: revision(store_id, bytes) };
  }
  baseline(sessionId: string): GeminiNativeBaseline {
    const saved = this.snapshot(sessionId);
    return { schema_version: "gemini.native_baseline.v1", session_id: sessionId, store_id: saved.store_id,
      revision: saved.revision, byte_length: saved.bytes.length, record_count: saved.records.length };
  }
  assertAppend(baseline: GeminiNativeBaseline) {
    requireThat(baseline.schema_version === "gemini.native_baseline.v1" && Number.isSafeInteger(baseline.byte_length)
      && baseline.byte_length > 0 && Number.isSafeInteger(baseline.record_count) && baseline.record_count > 0, "gemini_baseline_invalid");
    const current = this.snapshot(baseline.session_id);
    requireThat(current.store_id === baseline.store_id && current.bytes.length > baseline.byte_length
      && current.records.length > baseline.record_count && current.bytes[baseline.byte_length - 1] === 10
      && revision(current.store_id, current.bytes.subarray(0, baseline.byte_length)) === baseline.revision, "gemini_baseline_changed");
    requireThat(current.bytes.subarray(0, baseline.byte_length).filter(byte => byte === 10).length === baseline.record_count, "gemini_baseline_changed");
    const prior = replay(current.records.slice(0, baseline.record_count), baseline.session_id, geminiProjectHash(this.workspace));
    const oldIds = new Set(prior.messages.map(message => message.id));
    requireThat(current.records.slice(baseline.record_count).every(row => !Object.hasOwn(row, "$rewindTo")
      && !(object(row.$set) && Object.hasOwn(row.$set, "messages")) && !oldIds.has(row.id))
      && current.metadata.startTime === prior.metadata.startTime
      && digest(current.messages.slice(0, prior.messages.length)) === digest(prior.messages), "gemini_prior_context_changed");
    return { ...current, appended_messages: current.messages.slice(prior.messages.length) };
  }
}
