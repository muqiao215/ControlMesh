import type { RuntimeDatabase } from "./database";
import type { Principal } from "./kernel";
import { canonical, digest, identifier, requireThat } from "./value";

export function requireScope(actor: Principal, scope: string): void {
  identifier(actor.id);
  requireThat(["human_request", "agent_message", "schedule", "recovery", "internal"].includes(actor.origin), "invalid_origin");
  requireThat(actor.scopes.includes(scope), "scope_denied");
}

/** Authorization must be rechecked by the caller even when returning a stored receipt. */
export function command<T>(db: RuntimeDatabase, actor: Principal, requestId: string, operation: string,
  body: unknown, run: () => T, replay: (value: T) => T = value => value): T {
  identifier(requestId);
  const hash = digest({ operation, body, origin: actor.origin, device_id: actor.device_id ?? null });
  return db.transaction(() => {
    const previous = db.sql.query("SELECT * FROM receipts WHERE principal=? AND request_id=?").get(actor.id, requestId) as { digest: string; response: string } | null;
    if (previous) {
      requireThat(previous.digest === hash, "idempotency_conflict");
      return replay(JSON.parse(previous.response) as T);
    }
    const result = run();
    db.sql.query("INSERT INTO receipts VALUES (?, ?, ?, ?)").run(actor.id, requestId, hash, canonical(result));
    return result;
  });
}
