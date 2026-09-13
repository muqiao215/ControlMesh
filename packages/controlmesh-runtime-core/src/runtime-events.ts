import { parseRuntimeEventJson, runtimeEventJson } from "./runtime-event-json";
import { RuntimeDatabase } from "./database";
import { identifier, object, requireThat } from "./value";
import { runtimeSessionStorageKey } from "./runtime-session-key";

/** Internal persisted event shape; original wire fields are retained, including extra metadata. */
export interface BackstageEvent extends Record<string, unknown> {
  event_id: string; session_key: string; event_type: string; payload: Record<string, unknown>;
  created_at: string; transport: string; chat_id: string | number | bigint; topic_id: string | number | bigint | null;
}
function decode(value: unknown): BackstageEvent {
  requireThat(object(value), "invalid_runtime_event");
  for (const key of ["event_id", "session_key", "event_type", "created_at", "transport"]) requireThat(typeof value[key] === "string" && value[key].length > 0, "invalid_runtime_event");
  requireThat(object(value.payload) && (typeof value.chat_id === "string" || typeof value.chat_id === "bigint" || Number.isSafeInteger(value.chat_id))
    && (value.topic_id === null || typeof value.topic_id === "string" || typeof value.topic_id === "bigint" || Number.isSafeInteger(value.topic_id)), "invalid_runtime_event");
  runtimeSessionStorageKey(value.session_key as string);
  requireThat(Buffer.byteLength(runtimeEventJson(value)) <= 1024 * 1024, "runtime_event_too_large");
  return structuredClone(value) as BackstageEvent;
}
/** Separate from task kernel events. Principal isolation is explicit at every read/write. */
export class RuntimeEventStore {
  constructor(private readonly db: RuntimeDatabase) {}
  append(principal: string, raw: unknown): BackstageEvent {
    identifier(principal); const event = decode(raw), key = runtimeSessionStorageKey(event.session_key), payload = runtimeEventJson(event);
    return this.db.transaction(() => {
      const old = this.db.sql.query("SELECT payload FROM backstage_events WHERE principal=? AND event_id=?").get(principal, event.event_id) as { payload: string } | null;
      if (old) requireThat(old.payload === payload, "runtime_event_id_conflict");
      else this.db.sql.query("INSERT INTO backstage_events(principal,event_id,session_key,payload) VALUES(?,?,?,?)").run(principal, event.event_id, key, payload);
      return event;
    });
  }
  /** Migration input must come from one explicitly selected session, never inferred directories. */
  importJsonl(principal: string, session: string, text: string): { imported: number; replayed: number } {
    identifier(principal); const key = runtimeSessionStorageKey(session);
    requireThat(typeof text === "string" && Buffer.byteLength(text) <= 16 * 1024 * 1024, "runtime_event_import_too_large");
    const lines = text.split("\n").filter(line => line.trim());
    requireThat(lines.length <= 10000, "runtime_event_import_too_large");
    const events = lines.map(line => decode(parseRuntimeEventJson(line)));
    requireThat(events.every(event => runtimeSessionStorageKey(event.session_key) === key), "runtime_event_import_session_mismatch");
    return this.db.transaction(() => {
      let imported = 0;
      for (const event of events) {
        const exists = this.db.sql.query("SELECT 1 FROM backstage_events WHERE principal=? AND event_id=?").get(principal, event.event_id);
        this.append(principal, event); if (!exists) imported++;
      }
      return { imported, replayed: events.length - imported };
    });
  }
  exportJsonl(principal: string, session: string): string {
    return this.readRecent(principal, session, 0).map(event => runtimeEventJson(event) + "\n").join("");
  }
  /** Bounded controller page; before is exclusive and stable when newer events arrive. */
  readPage(principal: string, session: string, limit = 20, before?: number) {
    identifier(principal); const key = runtimeSessionStorageKey(session);
    requireThat(Number.isSafeInteger(limit) && limit >= 1 && limit <= 100, "invalid_local_event_limit");
    requireThat(before === undefined || (Number.isSafeInteger(before) && before > 0), "invalid_runtime_event_cursor");
    const selected: { seq: number; line: string }[] = [];
    let bytes = 0, has_more = false;
    const statement = this.db.sql.prepare("SELECT seq,payload FROM backstage_events WHERE principal=? AND session_key=? AND (? IS NULL OR seq<?) ORDER BY seq DESC LIMIT ?");
    try {
      const rows = statement.iterate(principal, key, before ?? null, before ?? null, limit + 1) as Iterable<{ seq: number; payload: string }>;
      for (const row of rows) {
        if (selected.length === limit) { has_more = true; break; }
        requireThat(Number.isSafeInteger(row.seq) && row.seq > 0 && Buffer.byteLength(row.payload) <= 1024 * 1024, "invalid_runtime_event_row");
        const line = runtimeEventJson(decode(parseRuntimeEventJson(row.payload))) + "\n", size = Buffer.byteLength(line);
        if (bytes + size > 2 * 1024 * 1024) { has_more = true; break; }
        selected.push({ seq: row.seq, line }); bytes += size;
      }
    } finally { statement.finalize(); }
    const next_before = has_more ? selected.at(-1)!.seq : null;
    return { session_key: key, count: selected.length, jsonl: selected.reverse().map(row => row.line).join(""), has_more, next_before };
  }
  readRecent(principal: string, session: string, limit = 20): BackstageEvent[] {
    identifier(principal); requireThat(Number.isSafeInteger(limit), "invalid_runtime_event_limit");
    const key = runtimeSessionStorageKey(session);
    const rows = this.db.sql.query("SELECT payload FROM backstage_events WHERE principal=? AND session_key=? ORDER BY seq DESC LIMIT ?")
      .all(principal, key, limit <= 0 ? -1 : limit) as { payload: string }[];
    return rows.reverse().map(row => decode(parseRuntimeEventJson(row.payload)));
  }
}
