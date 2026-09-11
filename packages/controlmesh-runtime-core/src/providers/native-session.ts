import { Database } from "bun:sqlite";
import { createHash } from "node:crypto";
import { realpathSync, statSync } from "node:fs";
import { isAbsolute } from "node:path";
import { canonical, digest, identifier, object, requireThat } from "../value";

export interface NativeSessionRef {
  schema_version: "agent.native_session.v2";
  provider: "opencode";
  device_id: string;
  store_id: string;
  session_id: string;
  directory: string;
  project_id: string;
  revision: string;
  model: string;
  title: string;
}

export interface NativeBaseline {
  reference: NativeSessionRef;
  messages: Record<string, string>;
  parts: Record<string, string>;
  permissions: unknown;
}

const MAX_BYTES = 32 * 1024 * 1024;
const MAX_ROWS = 100_000;
const quote = (value: string) => '"' + value.replaceAll('"', '""') + '"';

/** Same byte protocol as History Viewer's independent read-only implementation.
 * SQLite type + hex(value) avoids Python/JS float and Unicode serialization differences.
 * Hash every column and every message/part, including edits to older content.
 */
export function nativeContentRevision(db: Database, sessionId: string, storeId: string): string {
  const hash = createHash("sha256").update(canonical(["opencode-sqlite-content-v2", storeId]) + "\n");
  let bytes = 0, rows = 0;
  for (const table of ["session", "message", "part"]) {
    const columns = (db.query(`PRAGMA table_info(${table})`).all() as { name: string }[]).map(row => row.name).sort();
    requireThat(columns.includes("id") && columns.length <= 128 && columns.every(column => /^[A-Za-z_][A-Za-z0-9_]*$/.test(column)), "unsupported_native_schema");
    const fields = columns.flatMap(column => [`typeof(${quote(column)})`, `hex(${quote(column)})`]);
    const predicate = table === "session" ? "id" : "session_id";
    const query = db.query(`SELECT ${fields.join(",")} FROM ${table} WHERE ${predicate}=? ORDER BY id`);
    // Size checked in SQL before materializing the selected source content.
    const size = db.query(`SELECT COUNT(*) AS n, COALESCE(SUM(${columns.map(column => `length(CAST(${quote(column)} AS BLOB))`).join("+")}),0) AS bytes FROM ${table} WHERE ${predicate}=?`).get(sessionId) as { n: number; bytes: number };
    rows += size.n; bytes += size.bytes;
    requireThat(rows <= MAX_ROWS && bytes <= MAX_BYTES, "native_session_too_large");
    for (const values of query.values(sessionId)) {
      const cells = columns.map((column, i) => [column, values[2 * i], values[2 * i + 1]]);
      hash.update(canonical([table, cells]) + "\n");
    }
  }
  return hash.digest("hex");
}

/** Store path and device are supplied by local configuration, never by a remote candidate. */
export class NativeSessionStore {
  constructor(readonly path: string, readonly deviceId: string) {
    identifier(deviceId);
    requireThat(isAbsolute(path), "native_store_path_must_be_explicit");
  }

  read(sessionId: string): NativeSessionRef {
    return this.inspect(sessionId, (_db, reference) => reference);
  }

  identity(): string {
    const path = realpathSync(this.path), stat = statSync(path, { bigint: true });
    requireThat(stat.isFile(), "native_store_not_regular");
    return digest(["opencode-store-v2", this.deviceId, path, String(stat.dev), String(stat.ino)]);
  }

  private inspect<T>(sessionId: string, collect: (db: Database, reference: NativeSessionRef) => T): T {
    requireThat(/^ses_[A-Za-z0-9]{1,192}$/.test(sessionId), "invalid_native_session_id");
    const path = realpathSync(this.path);
    const before = statSync(path, { bigint: true });
    requireThat(before.isFile(), "native_store_not_regular");
    const storeId = digest(["opencode-store-v2", this.deviceId, path, String(before.dev), String(before.ino)]);
    const db = new Database(path, { readonly: true, strict: true });
    try {
      db.exec("PRAGMA query_only=ON; PRAGMA busy_timeout=2000; BEGIN");
      const row = db.query("SELECT id, directory, project_id, title, time_archived FROM session WHERE id=?").get(sessionId) as Record<string, unknown> | null;
      requireThat(row && !row.time_archived, "native_session_missing_or_archived");
      requireThat(typeof row.directory === "string" && isAbsolute(row.directory), "native_directory_unavailable");
      const directory = realpathSync(row.directory);
      requireThat(statSync(directory).isDirectory() && typeof row.project_id === "string", "native_directory_unavailable");
      const revision = nativeContentRevision(db, sessionId, storeId);
      const latest = db.query("SELECT data FROM message WHERE session_id=? AND json_valid(data) AND json_extract(data,'$.role')='assistant' ORDER BY time_created DESC,id DESC LIMIT 1").get(sessionId) as { data: string } | null;
      const model: unknown = latest ? JSON.parse(latest.data) : {};
      const after = statSync(this.path, { bigint: true });
      requireThat(realpathSync(this.path) === path && before.dev === after.dev && before.ino === after.ino, "native_store_replaced");
      const reference: NativeSessionRef = { schema_version: "agent.native_session.v2", provider: "opencode", device_id: this.deviceId,
        store_id: storeId, session_id: sessionId, directory, project_id: row.project_id, revision,
        model: object(model) && typeof model.providerID === "string" && typeof model.modelID === "string" ? `${model.providerID}/${model.modelID}` : "",
        title: typeof row.title === "string" ? Array.from(row.title).slice(0, 512).join("") : "" };
      return collect(db, reference);
    } finally { db.close(); }
  }

  baseline(ref: NativeSessionRef): NativeBaseline {
    return this.inspect(ref.session_id, (db, current) => {
      requireThat(digest(ref) === digest(current), "native_reference_changed");
      const hashes = (table: string) => Object.fromEntries((db.query(`SELECT * FROM ${table} WHERE session_id=? ORDER BY id`).all(ref.session_id) as Record<string, unknown>[])
        .map(row => [String(row.id), digest(row)]));
      const last = db.query("SELECT data FROM message WHERE session_id=? ORDER BY time_created DESC,id DESC LIMIT 1").get(ref.session_id) as { data: string } | null;
      if (last) {
        const message: unknown = JSON.parse(last.data);
        requireThat(object(message) && message.role === "assistant" && object(message.time) && typeof message.time.completed === "number" && message.finish === "stop" && !message.error, "native_session_not_idle");
      }
      const row = db.query("SELECT permission FROM session WHERE id=?").get(ref.session_id) as { permission: string | null };
      return { reference: current, messages: hashes("message"), parts: hashes("part"), permissions: row.permission ? JSON.parse(row.permission) : [] };
    });
  }

  /** Confirms an appended native turn, not semantic task acceptance or arbitrary external-client exclusion. */
  verifyTurn(sessionId: string, before: NativeBaseline | null, prompt: string, output: string): { reference: NativeSessionRef; user_message_id: string; assistant_message_ids: string[]; read_files: string[] } {
    return this.inspect(sessionId, (db, reference) => {
      if (before) {
        const old = before.reference;
        requireThat(reference.session_id === old.session_id && reference.device_id === old.device_id && reference.store_id === old.store_id && reference.directory === old.directory && reference.project_id === old.project_id, "native_identity_changed");
      }
      const messages = db.query("SELECT * FROM message WHERE session_id=? ORDER BY time_created,id").all(sessionId) as Record<string, unknown>[];
      const parts = db.query("SELECT * FROM part WHERE session_id=? ORDER BY time_created,id").all(sessionId) as Record<string, unknown>[];
      for (const [rows, expected] of [[messages, before?.messages], [parts, before?.parts]] as const) {
        if (!expected) continue;
        const current = new Map(rows.map(row => [String(row.id), digest(row)]));
        requireThat(Object.entries(expected).every(([id, hash]) => current.get(id) === hash), "native_prior_content_changed");
      }
      const added = messages.filter(row => !before?.messages[String(row.id)]).map(row => ({ id: String(row.id), data: JSON.parse(String(row.data)) as Record<string, unknown> }));
      const users = added.filter(row => row.data.role === "user");
      const assistants = added.filter(row => row.data.role === "assistant");
      requireThat(users.length === 1 && assistants.length > 0 && added.length === users.length + assistants.length, "native_concurrent_turn_or_missing_lineage");
      requireThat(assistants.every(row => row.data.parentID === users[0].id && !row.data.error), "native_assistant_parent_mismatch");
      const last = assistants.at(-1)!.data;
      requireThat(last.finish === "stop" && object(last.time) && typeof last.time.completed === "number", "native_turn_not_completed");
      const newParts = parts.filter(row => !before?.parts[String(row.id)]).map(row => ({ message: String(row.message_id), data: JSON.parse(String(row.data)) as Record<string, unknown> }));
      const assistantIds = assistants.map(row => row.id);
      requireThat(newParts.every(row => row.message === users[0].id || assistantIds.includes(row.message)), "native_unowned_part");
      const text = (ids: string[]) => newParts.filter(row => ids.includes(row.message) && row.data.type === "text").map(row => String(row.data.text ?? "")).join("");
      requireThat(text([users[0].id]) === prompt && text(assistantIds) === output, "native_turn_content_mismatch");
      const reads = newParts.filter(row => row.data.type === "tool" && row.data.tool === "read" && object(row.data.state) && row.data.state.status === "completed")
        .map(row => { const state = row.data.state as Record<string, unknown>; return object(state.input) && typeof state.input.filePath === "string" ? state.input.filePath : ""; }).filter(Boolean);
      return { reference, user_message_id: users[0].id, assistant_message_ids: assistantIds, read_files: [...new Set(reads)] };
    });
  }

  validate(ref: NativeSessionRef): NativeSessionRef {
    requireThat(ref.schema_version === "agent.native_session.v2" && ref.provider === "opencode", "unsupported_native_reference");
    requireThat(ref.device_id === this.deviceId, "native_device_mismatch");
    const current = this.read(ref.session_id);
    requireThat(current.store_id === ref.store_id && current.directory === ref.directory && current.project_id === ref.project_id, "native_identity_changed");
    requireThat(current.revision === ref.revision && current.model === ref.model, "native_revision_changed");
    return current;
  }

  worktree(ref: NativeSessionRef): string {
    return this.inspect(ref.session_id, (db, current) => {
      requireThat(current.store_id === ref.store_id && current.project_id === ref.project_id && current.directory === ref.directory, "native_identity_changed");
      if (ref.project_id === "global") {
        // OpenCode rewrites this shared project row whenever any non-project probe opens.
        // Empty Git repositories also use global; their ReadTool base is still the Git root.
        const git = Bun.spawnSync(["/usr/bin/git", "-C", current.directory, "rev-parse", "--show-toplevel"], {
          timeout: 2000, stdout: "pipe", stderr: "pipe",
          env: { PATH: "/usr/bin:/bin", LC_ALL: "C", GIT_CONFIG_NOSYSTEM: "1", GIT_CONFIG_GLOBAL: "/dev/null" },
        });
        if (git.exitCode === 0) return realpathSync(git.stdout.toString().trim());
        requireThat(git.exitCode === 128 && git.stderr.toString().startsWith("fatal: not a git repository (or any"), "native_worktree_unavailable");
        return "/";
      }
      const row = db.query("SELECT worktree FROM project WHERE id=?").get(ref.project_id) as { worktree: string } | null;
      requireThat(row && typeof row.worktree === "string" && isAbsolute(row.worktree), "native_worktree_unavailable");
      return realpathSync(row.worktree);
    });
  }
}
