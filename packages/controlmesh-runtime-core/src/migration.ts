import { createHash } from "node:crypto";
import { RuntimeDatabase } from "./database";
import { canonical, digest, identifier, legacyTask, object, requireThat, terminal, type LegacyTask } from "./value";

export interface ImportPreview {
  source_id: string;
  digest: string;
  task_count: number;
  active_task_ids: string[];
  statuses: Record<string, number>;
}

/** Reads a snapshot only; does not instantiate Python registries, delete folders, or take writer authority. */
export class LegacyMigration {
  constructor(private readonly db: RuntimeDatabase) {}

  preview(sourceId: string, source: unknown): ImportPreview {
    identifier(sourceId);
    requireThat(object(source) && Array.isArray(source.tasks), "invalid_legacy_registry");
    requireThat(source.tasks.length <= 100_000, "migration_too_large");
    const seen = new Set<string>();
    const counts: Record<string, number> = {};
    const active: string[] = [];
    for (const task of source.tasks) {
      legacyTask(task);
      requireThat(!seen.has(task.task_id), "duplicate_legacy_task");
      seen.add(task.task_id);
      counts[task.status] = (counts[task.status] ?? 0) + 1;
      if (!terminal.has(task.status)) active.push(task.task_id);
    }
    return { source_id: sourceId, digest: digest(source), task_count: seen.size, active_task_ids: active, statuses: counts };
  }

  importSnapshot(sourceId: string, source: unknown, expectedDigest: string, principal: string): ImportPreview {
    identifier(principal);
    const preview = this.preview(sourceId, source);
    requireThat(preview.digest === expectedDigest, "migration_source_changed");
    return this.db.transaction(() => {
      const prior = this.db.sql.query("SELECT digest FROM migrations WHERE source_id=?").get(sourceId) as { digest: string } | null;
      if (prior) {
        requireThat(prior.digest === expectedDigest, "migration_conflict");
        return preview;
      }
      requireThat(!this.db.sql.query("SELECT 1 FROM tasks LIMIT 1").get(), "migration_target_not_empty");
      const tasks = (source as { tasks: LegacyTask[] }).tasks;
      for (const task of tasks) {
        this.db.sql.query("INSERT INTO tasks (task_id,principal,revision,status,needs_reconciliation,raw) VALUES (?,?,1,?,?,?)")
          .run(task.task_id, principal, task.status, terminal.has(task.status) ? 0 : 1, canonical(task));
      }
      // Original envelope is retained, including fields this runtime does not yet understand.
      this.db.sql.query("INSERT INTO migrations VALUES (?,?,?,?)").run(sourceId, expectedDigest, canonical(source), tasks.length);
      return preview;
    });
  }

  originalSnapshot(sourceId: string): unknown {
    const row = this.db.sql.query("SELECT snapshot FROM migrations WHERE source_id=?").get(sourceId) as { snapshot: string } | null;
    requireThat(row, "migration_not_found");
    return JSON.parse(row.snapshot);
  }

  /** Compatibility export, not permission to restart an old writer. Retains unknown envelope/row fields. */
  exportSnapshot(sourceId: string): unknown {
    const original = this.originalSnapshot(sourceId) as Record<string, unknown>;
    const rows = this.db.sql.query("SELECT raw FROM tasks ORDER BY rowid").all() as { raw: string }[];
    return { ...original, tasks: rows.map(row => JSON.parse(row.raw)) };
  }
}

export function decodeSnapshot(bytes: Uint8Array): { source: unknown; file_digest: string } {
  requireThat(bytes.byteLength <= 64 * 1024 * 1024, "migration_file_too_large");
  const text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  // JSON syntax errors and invalid UTF-8 must not become an empty registry.
  const source: unknown = JSON.parse(text);
  // JSON.parse otherwise accepts duplicate keys with last-value-wins semantics.
  let cursor = 0;
  const whitespace = () => { while (/\s/.test(text[cursor] ?? "x")) cursor++; };
  const string = () => {
    const start = cursor++;
    while (text[cursor] !== '"') {
      if (text[cursor] === "\\") cursor++;
      cursor++;
    }
    cursor++;
    return JSON.parse(text.slice(start, cursor)) as string;
  };
  const visit = (depth: number) => {
    requireThat(depth <= 64, "migration_nesting_too_deep");
    whitespace();
    const opening = text[cursor];
    if (opening === "{" || opening === "[") {
      cursor++;
      whitespace();
      const closing = opening === "{" ? "}" : "]";
      const keys = new Set<string>();
      while (text[cursor] !== closing) {
        if (opening === "{") {
          const key = string();
          requireThat(!keys.has(key), "duplicate_json_key");
          keys.add(key);
          whitespace();
          cursor++; // colon; JSON.parse has already checked grammar
        }
        visit(depth + 1);
        whitespace();
        if (text[cursor] !== ",") break;
        cursor++;
        whitespace();
      }
      cursor++;
    } else if (opening === '"') {
      string();
    } else {
      while (cursor < text.length && !/[\s,\]}]/.test(text[cursor])) cursor++;
    }
  };
  visit(0);
  canonical(source);
  return { source, file_digest: createHash("sha256").update(bytes).digest("hex") };
}
