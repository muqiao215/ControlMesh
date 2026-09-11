import { randomUUID } from "node:crypto";
import { assertProtocolSchema, type DeviceCommand, type DeviceLeaseWindow, type DeviceResponse } from "@controlmesh/protocol";
import type { Lease } from "./kernel";
import type { DeviceJob } from "./device-coordinator";
import { elapsedMs } from "./elapsed-clock";
import { canonical, digest, identifier, object, requireThat, RuntimeConflict } from "./value";

export interface DeviceClientOptions {
  endpoint: string;
  token: string;
  device_id: string;
  timeout_ms?: number;
  elapsed?: () => number;
  fetch?: typeof fetch;
}
export class DeviceClient {
  readonly deviceId: string;
  readonly clock: () => number;
  private readonly endpoint: string;
  private readonly token: string;
  private readonly timeout: number;
  private readonly fetcher: typeof fetch;

  constructor(options: DeviceClientOptions) {
    const url = new URL(options.endpoint);
    requireThat(!url.username && !url.password && !url.hash && !url.search && (url.pathname === "/" || url.pathname === ""), "invalid_coordinator_endpoint");
    requireThat(url.protocol === "https:" || (url.protocol === "http:" && ["127.0.0.1", "[::1]"].includes(url.hostname)), "encrypted_or_loopback_transport_required");
    requireThat(/^[A-Za-z0-9_-]{43,128}$/.test(options.token), "invalid_device_credential");
    identifier(options.device_id);
    this.endpoint = `${url.origin}/worker/v1/command`;
    this.token = options.token;
    this.deviceId = options.device_id;
    this.timeout = options.timeout_ms ?? 3000;
    requireThat(Number.isSafeInteger(this.timeout) && this.timeout >= 100 && this.timeout <= 10_000, "invalid_transport_timeout");
    this.clock = options.elapsed ?? elapsedMs;
    this.fetcher = options.fetch ?? fetch;
  }

  /** Never retries mutations automatically. Callers retain an ID only to inspect/replay that exact operation. */
  async command(operation: DeviceCommand["operation"], args: Record<string, unknown>, requestId: string = randomUUID()): Promise<unknown> {
    const input: DeviceCommand = { schema_version: "controlmesh.device_command.v1", request_id: requestId, operation, arguments: args };
    assertProtocolSchema("device-command.schema.json", input);
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.timeout);
    try {
      const response = await this.fetcher(this.endpoint, { method: "POST", redirect: "error", credentials: "omit", cache: "no-store",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${this.token}` }, body: canonical(input), signal: controller.signal });
      requireThat(response.headers.get("Content-Type")?.startsWith("application/json"), "invalid_coordinator_response");
      requireThat(response.body, "invalid_coordinator_response");
      const reader = response.body.getReader();
      let bytes = 0;
      const chunks: Uint8Array[] = [];
      try {
        while (true) {
          const next = await reader.read();
          if (next.done) break;
          bytes += next.value.length;
          requireThat(bytes <= 1_310_720, "coordinator_response_too_large");
          chunks.push(next.value);
        }
      } finally { void reader.cancel().catch(() => {}); }
      const output: unknown = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(Buffer.concat(chunks)));
      assertProtocolSchema<DeviceResponse>("device-response.schema.json", output);
      canonical(output);
      if (!output.ok) {
        requireThat(typeof output.error === "string" && /^[a-z0-9_]{1,96}$/.test(output.error) && !response.ok, "invalid_coordinator_response");
        throw new RuntimeConflict(output.error);
      }
      requireThat(response.ok && output.request_id === requestId && Object.hasOwn(output, "data"), "invalid_coordinator_response");
      return output.data;
    } catch (error) {
      if (error instanceof RuntimeConflict) throw error;
      throw new RuntimeConflict("coordinator_transport_unknown");
    } finally { clearTimeout(timeout); }
  }

  async inspect(taskId: string): Promise<DeviceJob> {
    const value = await this.command("inspect", { task_id: taskId });
    requireThat(object(value) && value.task_id === taskId && typeof value.status === "string" && Number.isSafeInteger(value.revision) && object(value.input), "invalid_device_job");
    identifier(value.workspace_id); identifier(value.capability);
    requireThat(typeof value.assignment_digest === "string" && /^[a-f0-9]{64}$/.test(value.assignment_digest), "invalid_device_job");
    if (value.execution !== undefined || value.execution_digest !== undefined) {
      requireThat(object(value.execution) && digest(value.execution) === value.execution_digest, "device_execution_projection_changed");
    }
    return value as unknown as DeviceJob;
  }

  async claim(taskId: string, revision: number, assignmentDigest: string, ttlMs: number, requestId: string = randomUUID()): Promise<DeviceLeaseAuthority> {
    const sent = this.clock();
    const output = await this.command("claim", { task_id: taskId, revision, assignment_digest: assignmentDigest, ttl_ms: ttlMs }, requestId);
    return new DeviceLeaseAuthority(this, taskId, ttlMs, sent, output);
  }
}

/** Synchronous process-admission guard over asynchronously renewed coordinator authority. */
export class DeviceLeaseAuthority {
  private proof!: Lease;
  private deadline = 0;
  private lastTime = 0;
  private closed = false;
  private initialized = false;
  private updating = false;
  readonly signal: AbortSignal;
  private readonly abort = new AbortController();

  constructor(private readonly client: DeviceClient, private readonly taskId: string, readonly ttlMs: number, sent: number, output: unknown) {
    this.signal = this.abort.signal;
    this.accept(sent, output);
  }
  get lease(): Lease { return structuredClone(this.proof); }

  private now(): number {
    const now = this.client.clock();
    if (!Number.isFinite(now) || now < this.lastTime) { this.stop(); throw new RuntimeConflict("worker_clock_invalid"); }
    this.lastTime = now;
    return now;
  }
  private accept(sent: number, output: unknown): void {
    if (this.initialized) this.assertCurrent();
    assertProtocolSchema<DeviceLeaseWindow>("device-lease-window.schema.json", output);
    const { lease, remaining_ms } = output;
    requireThat(lease.device_id === this.client.deviceId && lease.task_id === this.taskId && remaining_ms <= this.ttlMs, "lease_response_mismatch");
    if (this.initialized) requireThat(lease.episode_id === this.proof.episode_id && lease.fence === this.proof.fence, "lease_response_mismatch");
    // Start before network send: subtracting the full RTT is deliberately conservative.
    // /proc/uptime has centisecond precision; reserve 50 ms for quantization and dispatch.
    const deadline = sent + remaining_ms - 50;
    requireThat(Number.isFinite(sent) && sent >= 0 && this.now() < deadline && !this.closed, "worker_lease_expired");
    this.proof = structuredClone(lease);
    this.deadline = deadline;
    this.initialized = true;
  }
  assertCurrent = (): void => {
    if (this.closed || this.now() >= this.deadline) { this.stop(); throw new RuntimeConflict("worker_lease_expired"); }
  };
  remainingMs = (): number => { this.assertCurrent(); return Math.max(0, this.deadline - this.now()); };
  stop(): void { this.closed = true; this.abort.abort(); }

  private async update(operation: "start" | "renew", requestId: string): Promise<void> {
    this.assertCurrent();
    requireThat(!this.updating, "lease_update_in_flight");
    this.updating = true;
    const sent = this.now();
    try {
      const args: Record<string, unknown> = { lease: this.lease };
      if (operation === "renew") args.ttl_ms = this.ttlMs;
      this.accept(sent, await this.client.command(operation, args, requestId));
    } catch (error) { this.stop(); throw error; }
    finally { this.updating = false; }
  }
  start(requestId: string = randomUUID()): Promise<void> { return this.update("start", requestId); }
  renew(requestId: string = randomUUID()): Promise<void> { return this.update("renew", requestId); }
}
