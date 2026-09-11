import type { DeliveryOutbox } from "./delivery-outbox";
import type { FeishuInbox } from "./feishu-inbox";
import type { LocalTaskRuntime } from "./local-task-runtime";
import { requireThat, RuntimeConflict } from "./value";

/** Loopback webhook and event-driven work pump. No cron, polling model call, or reclassification as local input. */
export class FeishuInboundRuntime {
  private server: ReturnType<typeof Bun.serve> | undefined;
  private pumping: Promise<void> | undefined;
  private dirty = false;
  private stopping = false;
  private activeRequests = 0;
  private failure: string | null = null;
  constructor(readonly inbox: FeishuInbox, private readonly runtime: LocalTaskRuntime, private readonly deliveries: DeliveryOutbox,
    private readonly adapterId: string, private readonly path = "/feishu/events", private readonly port = 0) {
    requireThat(/^\/[A-Za-z0-9/_-]{1,127}$/.test(path), "invalid_feishu_event_path");
  }
  start(port = this.port): { hostname: string; port: number; path: string } {
    requireThat(!this.stopping && !this.server && Number.isInteger(port) && port >= 0 && port <= 65535, "invalid_feishu_listener_state");
    this.server = Bun.serve({ hostname: "127.0.0.1", port, maxRequestBodySize: 65_536, idleTimeout: 10, fetch: request => this.handle(request) });
    this.kick();
    return { hostname: "127.0.0.1", port: this.server.port!, path: this.path };
  }
  private async handle(request: Request): Promise<Response> {
    if (new URL(request.url).pathname !== this.path || request.method !== "POST") return new Response(null, { status: 404 });
    if (this.stopping) return new Response(null, { status: 503 });
    if (this.activeRequests >= 8) return new Response(null, { status: 429 });
    if (request.headers.get("content-type")?.split(";")[0].trim().toLowerCase() !== "application/json") return new Response(null, { status: 415 });
    this.activeRequests++;
    try {
      const bytes = new Uint8Array(await request.arrayBuffer());
      requireThat(!this.stopping, "feishu_ingress_stopping");
      const result = this.inbox.receive(request.headers, bytes);
      if ("accepted" in result && result.accepted) this.kick();
      return Response.json(result);
    } catch (error) {
      // Never return padding/auth distinctions or provider content to an unauthenticated client.
      const full = error instanceof RuntimeConflict && error.code === "feishu_inbox_full";
      return Response.json({ error: full ? "ingress_backpressure" : "event_rejected" }, { status: full ? 503 : 400 });
    } finally { this.activeRequests--; }
  }
  kick(): void {
    if (this.stopping) return;
    this.dirty = true;
    if (this.pumping) return;
    this.pumping = (async () => {
      do {
        this.dirty = false;
        const applied = this.inbox.applyPending(this.runtime, this.deliveries, this.adapterId);
        const before = this.runtime.queueStatus();
        await this.runtime.drain();
        if (this.stopping) break;
        await this.deliveries.drain();
        const after = this.runtime.queueStatus();
        // Reopened queued work can release a conversation even when this pass applied no new event.
        if ((applied || after.queued + after.running < before.queued + before.running) && this.inbox.status().pending) this.dirty = true;
      } while (this.dirty && !this.stopping);
      this.failure = null;
    })().catch(error => {
      this.failure = error instanceof RuntimeConflict ? error.code : "feishu_ingress_processing_failed";
    }).finally(() => { this.pumping = undefined; if (this.dirty && !this.stopping) this.kick(); });
  }
  async drain(): Promise<void> { this.kick(); while (this.pumping) await this.pumping; }
  status() { return { ...this.inbox.status(), processing: Boolean(this.pumping), failure: this.failure,
    listener: this.server ? { hostname: "127.0.0.1", port: this.server.port, path: this.path } : null, blocked_items: this.inbox.listBlocked() }; }
  retry(requestId: string, id: string): void { this.inbox.retry(requestId, id); this.kick(); }
  async stop(): Promise<void> {
    this.stopping = true;
    await this.server?.stop(true); this.server = undefined;
    // The shared runtime owner stops execution/delivery concurrently before awaiting this pump.
    await this.pumping;
  }
}
