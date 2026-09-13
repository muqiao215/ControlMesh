import { randomUUID } from "node:crypto";
import type { RuntimeKernel, Principal } from "./kernel";
import type { DeliveryContext, DeliveryOutbox } from "./delivery-outbox";
import type { LocalTaskRuntime } from "./local-task-runtime";
import { TelegramInbox } from "./telegram-inbox";
import { WebhookInboundRuntime } from "./feishu-inbound-runtime";
import { canonical, digest, object, requireThat, RuntimeConflict } from "./value";
import { requireScope } from "./commands";

export interface TelegramPollingCredentials {
  botToken(context: DeliveryContext): Promise<string>; assertToken(token: string): void;
}
interface PollState { bot_id: string; principal: string; binding_digest: string; next_offset: number; last_update_at: number;
  owner: string | null; generation: number; lease_until: number; next_poll_at: number; failures: number; failure: string | null }

/** One local-store polling owner. Offsets acknowledge only fully persisted batches. */
export class TelegramPollingRuntime {
  private readonly owner = randomUUID();
  private readonly actor: Principal;
  private readonly pump: WebhookInboundRuntime;
  private readonly binding: string;
  private running: Promise<void> | undefined;
  private inflight: Promise<number> | undefined;
  private abort: AbortController | undefined;
  private stopped = false;
  private wake: (() => void) | undefined;
  constructor(private readonly kernel: RuntimeKernel, actor: Principal, readonly inbox: TelegramInbox,
    runtime: LocalTaskRuntime, deliveries: DeliveryOutbox, adapterId: string,
    private readonly credentials: TelegramPollingCredentials, private readonly current: () => void, private readonly request: typeof fetch = fetch) {
    this.actor = structuredClone(actor); this.binding = digest({ kind: "telegram_polling.v1", inbox: inbox.binding_digest });
    this.pump = new WebhookInboundRuntime(inbox, runtime, deliveries, adapterId, "/telegram/events", 0, "telegram");
    this.check();
    this.kernel.db.transaction(() => {
      this.kernel.db.sql.query("INSERT OR IGNORE INTO telegram_polling(bot_id,principal,binding_digest) VALUES (?,?,?)")
        .run(inbox.bot_id, actor.id, this.binding); this.state();
    });
  }
  private check() {
    requireScope(this.actor, "telegram:ingest"); requireThat(!this.stopped, "telegram_polling_stopped");
    const checked: unknown = this.current();
    if (checked !== undefined) { void Promise.resolve(checked).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
  }
  private state(): PollState {
    const row = this.kernel.db.sql.query("SELECT * FROM telegram_polling WHERE bot_id=?").get(this.inbox.bot_id) as PollState;
    requireThat(row && row.principal === this.actor.id && row.binding_digest === this.binding, "telegram_polling_registration_changed"); return row;
  }
  start(): { mode: "polling"; bot_id: string } {
    this.check(); requireThat(!this.running, "telegram_polling_already_started");
    requireThat(this.actor.origin === "human_request" || this.actor.origin === "internal", "telegram_polling_start_denied");
    this.kernel.db.transaction(() => {
      const row = this.state(); requireThat(!row.owner || row.lease_until <= this.kernel.db.now(), "telegram_polling_owned");
      this.kernel.db.sql.query("UPDATE telegram_polling SET failures=0,failure=NULL,next_poll_at=0 WHERE bot_id=?").run(this.inbox.bot_id);
    });
    this.pump.kick();
    this.running = (async () => {
      while (!this.stopped) {
        try { await this.pollOnce(); } catch { break; }
        if (this.stopped || this.state().failure) break;
        const delay = Math.max(500, Math.min(60000, this.state().next_poll_at - this.kernel.db.now()));
        await new Promise<void>(resolve => { const timer = setTimeout(() => { this.wake = undefined; resolve(); }, delay);
          this.wake = () => { clearTimeout(timer); this.wake = undefined; resolve(); }; });
      }
    })().finally(() => { this.running = undefined; });
    return { mode: "polling", bot_id: this.inbox.bot_id };
  }
  pollOnce(): Promise<number> {
    this.check(); if (this.inflight) return this.inflight;
    this.inflight = this.poll().finally(() => { this.inflight = undefined; }); return this.inflight;
  }
  private async poll(): Promise<number> {
    const lease = this.kernel.db.transaction(() => {
      this.check(); const row = this.state(), now = this.kernel.db.now();
      requireThat(!row.failure, "telegram_polling_paused");
      if (row.next_poll_at > now || (row.owner && row.lease_until > now)) return null;
      this.kernel.db.sql.query("UPDATE telegram_polling SET owner=?,generation=generation+1,lease_until=? WHERE bot_id=?")
        .run(this.owner, now + 60000, this.inbox.bot_id); return this.state();
    });
    if (!lease) return 0;
    const abort = new AbortController(); this.abort = abort;
    const timeout = setTimeout(() => abort.abort(), 30000);
    const admit = () => {
      this.check(); const row = this.state(); requireThat(!abort.signal.aborted && row.owner === this.owner
        && row.generation === lease.generation && row.lease_until > this.kernel.db.now(), "telegram_polling_authority_lost");
    };
    let retryAfter = 5000;
    try {
      admit(); const token = await this.credentials.botToken({ signal: abort.signal, assertCurrent: admit });
      const current = () => { admit(); const checked: unknown = this.credentials.assertToken(token);
        if (checked !== undefined) { void Promise.resolve(checked).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
        requireThat(typeof token === "string" && /^[1-9][0-9]*:[A-Za-z0-9_-]{16,256}$/.test(token)
          && token.split(":")[0] === this.inbox.bot_id, "telegram_token_identity_mismatch"); };
      const call = async (method: string, body: object): Promise<unknown> => {
        current(); let response: Response;
        try { response = await this.request(`https://api.telegram.org/bot${token}/${method}`, { method: "POST", redirect: "error",
          signal: abort.signal, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); }
        catch { throw new RuntimeConflict("telegram_polling_network_failed"); }
        requireThat(response.body, "telegram_polling_response_missing"); const reader = response.body.getReader();
        const chunks: Uint8Array[] = []; let size = 0;
        try { while (true) { const item = await reader.read(); if (item.done) break; size += item.value.length;
          requireThat(size <= 8 * 1024 * 1024, "telegram_polling_response_too_large"); chunks.push(item.value); } }
        finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
        current(); let data: unknown;
        try { data = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(Buffer.concat(chunks))); }
        catch { throw new RuntimeConflict("telegram_polling_response_invalid"); }
        if (object(data) && data.ok === false && data.error_code === 429 && object(data.parameters)
          && Number.isSafeInteger(data.parameters.retry_after) && Number(data.parameters.retry_after) > 0)
          { const requestedDelay = Number(data.parameters.retry_after) * 1000;
            requireThat(Number.isSafeInteger(requestedDelay) && requestedDelay <= 86400000, "telegram_polling_retry_after_requires_review");
            retryAfter = requestedDelay; }
        requireThat(response.status !== 401 && !(object(data) && data.error_code === 401), "telegram_polling_auth_failed");
        requireThat(response.status !== 409 && !(object(data) && data.error_code === 409), "telegram_polling_mode_conflict");
        requireThat(!(object(data) && data.error_code === 429), "telegram_polling_rate_limited");
        requireThat(response.ok && object(data) && data.ok === true, "telegram_polling_api_rejected"); return data.result;
      };
      const webhook = await call("getWebhookInfo", {});
      requireThat(object(webhook) && webhook.url === "", "telegram_polling_webhook_active");
      // Reset the query after a day without received updates, before Telegram's week-long
      // inactivity randomizes update IDs. Retained duplicates still dedupe locally.
      const offset = lease.last_update_at && this.kernel.db.now() - lease.last_update_at >= 86400000 ? 0 : lease.next_offset;
      const updates = await call("getUpdates", { offset, timeout: 25, limit: 100, allowed_updates: ["message", "callback_query"] });
      requireThat(Array.isArray(updates) && updates.length <= 100, "telegram_polling_batch_invalid");
      const accepted = this.kernel.db.transaction(() => {
        current(); let next = offset, count = 0, previous = -1;
        for (const update of updates) {
          requireThat(object(update) && Number.isSafeInteger(update.update_id) && Number(update.update_id) >= offset
            && Number(update.update_id) > previous && Number(update.update_id) < Number.MAX_SAFE_INTEGER, "telegram_polling_update_order_invalid");
          previous = Number(update.update_id); next = previous + 1;
          const payload = canonical(update), hash = digest(update);
          const prior = this.kernel.db.sql.query("SELECT payload_digest FROM telegram_poll_updates WHERE bot_id=? AND update_id=?")
            .get(this.inbox.bot_id, previous) as { payload_digest: string } | null;
          if (prior) requireThat(prior.payload_digest === hash, "telegram_polling_update_conflict");
          const received = this.inbox.receivePolled(Buffer.from(payload), current);
          if (received.accepted) count++;
          this.kernel.db.sql.query("INSERT OR IGNORE INTO telegram_poll_updates VALUES (?,?,?,?,?,?,?)")
            .run(this.inbox.bot_id, previous, payload, hash, received.accepted ? "accepted" : "ignored", received.reason ?? null, this.kernel.db.now());
        }
        current(); this.kernel.db.sql.query("UPDATE telegram_polling SET next_offset=?,last_update_at=?,failures=0,next_poll_at=0 WHERE bot_id=?")
          .run(updates.length ? next : lease.next_offset, updates.length ? this.kernel.db.now() : lease.last_update_at, this.inbox.bot_id);
        return count;
      });
      this.pump.kick(); return accepted;
    } catch (error) {
      const reason = error instanceof RuntimeConflict ? error.code : "telegram_polling_unavailable";
      this.kernel.db.transaction(() => {
        const row = this.state(); if (row.owner !== this.owner || row.generation !== lease.generation || this.stopped) return;
        const hard = !["telegram_polling_network_failed", "telegram_polling_api_rejected", "telegram_polling_rate_limited", "telegram_inbox_full"].includes(reason);
        this.kernel.db.sql.query("UPDATE telegram_polling SET failures=failures+1,failure=?,next_poll_at=? WHERE bot_id=?")
          .run(hard || row.failures >= 2 ? reason : null, this.kernel.db.now() + retryAfter, this.inbox.bot_id);
      });
      if (reason === "telegram_inbox_full") this.pump.kick();
      return 0;
    } finally {
      clearTimeout(timeout); this.abort = undefined;
      this.kernel.db.sql.query("UPDATE telegram_polling SET owner=NULL,lease_until=0 WHERE bot_id=? AND owner=? AND generation=?")
        .run(this.inbox.bot_id, this.owner, lease.generation);
    }
  }
  async drain() { await this.pollOnce(); await this.pump.drain(); }
  retry(requestId: string, id: string) { this.inbox.retry(requestId, id); this.pump.kick(); }
  status() { this.check(); const state = this.state(); return { ...this.pump.status(), mode: "polling", polling: Boolean(this.inflight),
    next_offset: state.next_offset, next_poll_at: state.next_poll_at, polling_failure: state.failure, failures: state.failures }; }
  async stop() { this.stopped = true; this.abort?.abort(); this.wake?.(); await this.inflight; await this.running; await this.pump.stop(); }
}
