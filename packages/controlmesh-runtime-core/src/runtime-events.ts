import { RuntimeDatabase } from "./database";
import { canonical, identifier, object, requireThat } from "./value";
import { runtimeSessionStorageKey } from "./runtime-session-key";

/** Internal persisted event shape; original wire fields are retained, including extra metadata. */
export interface BackstageEvent extends Record<string, unknown> {
  event_id: string; session_key: string; event_type: string; payload: Record<string, unknown>;
  created_at: string; transport: string; chat_id: string | number; topic_id: string | number | null;
}
function decode(value: unknown): BackstageEvent {
  requireThat(object(value), "invalid_runtime_event");
  for (const key of ["event_id", "session_key", "event_type", "created_at", "transport"]) requireThat(typeof value[key] === "string" && value[key].length > 0, "invalid_runtime_event");
  requireThat(object(value.payload) && (typeof value.chat_id === "string" || Number.isSafeInteger(value.chat_id))
    && (value.topic_id === null || typeof value.topic_id === "string" || Number.isSafeInteger(value.topic_id)), "invalid_runtime_event");
  runtimeSessionStorageKey(value.session_key as string);
  requireThat(Buffer.byteLength(canonical(value)) <= 1024 * 1024, "runtime_event_too_large");
  return structuredClone(value) as BackstageEvent;
}
/** Separate from task kernel events. Principal isolation is explicit at every read/write. */
export class RuntimeEventStore {
  constructor(private readonly db: RuntimeDatabase) {}
  append(principal: string, raw: unknown): BackstageEvent {
    identifier(principal); const event = decode(raw), key = runtimeSessionStorageKey(event.session_key), payload = canonical(event);
    return this.db.transaction(() => {
      const old = this.db.sql.query("SELECT payload FROM backstage_events WHERE principal=? AND event_id=?").get(principal, event.event_id) as { payload: string } | null;
      if (old) requireThat(old.payload === payload, "runtime_event_id_conflict");
      else this.db.sql.query("INSERT INTO backstage_events(principal,event_id,session_key,payload) VALUES(?,?,?,?)").run(principal, event.event_id, key, payload);
      return event;
    });
  }
  readRecent(principal: string, session: string, limit = 20): BackstageEvent[] {
    identifier(principal); requireThat(Number.isSafeInteger(limit), "invalid_runtime_event_limit");
    const key = runtimeSessionStorageKey(session);
    const rows = this.db.sql.query("SELECT payload FROM backstage_events WHERE principal=? AND session_key=? ORDER BY seq DESC LIMIT ?")
      .all(principal, key, limit <= 0 ? -1 : limit) as { payload: string }[];
    return rows.reverse().map(row => decode(JSON.parse(row.payload)));
  }
}
