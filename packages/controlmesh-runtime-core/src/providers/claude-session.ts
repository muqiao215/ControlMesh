import { createHash } from "node:crypto";
import { closeSync, constants, fstatSync, lstatSync, openSync, readSync, realpathSync, statSync, type BigIntStats } from "node:fs";
import { basename, isAbsolute } from "node:path";
import { canonical, digest, identifier, object, requireThat } from "../value";
import type { NativeSessionRef } from "./native-session";

export type ClaudeSessionRef = NativeSessionRef<"claude">;
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
}
