import type { RuntimeDatabase } from "./database";
import type { Principal } from "./kernel";
import { canonical, digest, identifier, requireThat } from "./value";

export function requireScope(actor: Principal, scope: string): void {
  identifier(actor.id);
  requireThat(["human_request", "agent_message", "schedule", "recovery", "internal"].includes(actor.origin), "invalid_origin");
  requireThat(actor.scopes.includes(scope), "scope_denied");
}

/** Authorization must be rechecked by the caller even when returning a stored receipt. */
export function commandReceipt<T>(db: RuntimeDatabase, actor: Principal, requestId: string, operation: string, body: unknown): { value: T } | null {
  identifier(requestId);
  const hash = digest({ operation, body, origin: actor.origin, device_id: actor.device_id ?? null });
  const reservation = db.sql.query("SELECT digest FROM command_reservations WHERE principal=? AND request_id=?").get(actor.id, requestId) as { digest: string } | null;
  requireThat(!reservation || reservation.digest === hash, "idempotency_conflict");
  const previous = db.sql.query("SELECT digest,response FROM receipts WHERE principal=? AND request_id=?").get(actor.id, requestId) as { digest: string; response: string } | null;
  if (!previous) return null;
  requireThat(previous.digest === hash, "idempotency_conflict");
  return { value: JSON.parse(previous.response) as T };
}

/** Reserve before asynchronous verification or filesystem effects; completion consumes this reservation atomically. */
export function reserveCommand(db: RuntimeDatabase, actor: Principal, requestId: string, operation: string, body: unknown): void {
  db.transaction(() => {
    if (commandReceipt(db, actor, requestId, operation, body)) return;
    db.sql.query("INSERT OR IGNORE INTO command_reservations VALUES (?,?,?)").run(actor.id, requestId,
      digest({ operation, body, origin: actor.origin, device_id: actor.device_id ?? null }));
  });
}

/** Authorization must be rechecked by the caller even when returning a stored receipt. */
export function command<T>(db: RuntimeDatabase, actor: Principal, requestId: string, operation: string,
  body: unknown, run: () => T, replay: (value: T) => T = value => value): T {
  identifier(requestId);
  const hash = digest({ operation, body, origin: actor.origin, device_id: actor.device_id ?? null });
  return db.transaction(() => {
    const previous = commandReceipt<T>(db, actor, requestId, operation, body);
    if (previous) return replay(previous.value);
    const result = run();
    db.sql.query("INSERT INTO receipts VALUES (?, ?, ?, ?)").run(actor.id, requestId, hash, canonical(result));
    db.sql.query("DELETE FROM command_reservations WHERE principal=? AND request_id=?").run(actor.id, requestId);
    return result;
  });
}
