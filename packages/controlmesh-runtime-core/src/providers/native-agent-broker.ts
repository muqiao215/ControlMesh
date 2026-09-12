import { randomBytes, timingSafeEqual } from "node:crypto";
import { chmodSync, closeSync, constants, lstatSync, openSync, unlinkSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { createServer, type Server, type IncomingMessage, type ServerResponse } from "node:http";
import { setTimeout as delay } from "node:timers/promises";
import type { RuntimeKernel, Principal, Lease } from "../kernel";
import { canonical, digest, identifier, object, requireThat, RuntimeConflict } from "../value";
import { NativeAgentJournal, type NativeAgentScope } from "./native-agent-journal";
import { assertNativeAgentConfiguration, nativeAgentScope, type NativeAgentConfiguration } from "./native-agent-profile";

/** Per-execution local capability. The model cannot choose the sender, principal or lease. */
export class NativeAgentChannel {
  readonly scope: NativeAgentScope;
  readonly command: string[];
  private readonly token = randomBytes(32).toString("hex");
  private readonly identity: string;
  private readonly socketName = `${randomBytes(16).toString("hex")}.sock`;
  private readonly configurationPath: string;
  private readonly directoryFd: number;
  private readonly server: Server;
  private readonly abort = new AbortController();
  private readonly active = new Map<string, { digest: string; promise: Promise<Record<string, unknown>> }>();
  private closed = false;
  private started = false;
  private socketIdentity?: { dev: number; ino: number };
  private configurationIdentity?: { dev: number; ino: number };

  constructor(lease: Pick<Lease, "task_id" | "episode_id" | "fence">,
    private readonly config: NativeAgentConfiguration, private readonly assertCurrent: () => void,
    private readonly backend: { assertDispatched: () => void; call: (tool: string, input: Record<string, unknown>, signal: AbortSignal) => Promise<Record<string, unknown>> }) {
    this.identity = assertNativeAgentConfiguration(config);
    this.scope = nativeAgentScope(config, lease);
    this.directoryFd = openSync(config.directory, constants.O_RDONLY | constants.O_DIRECTORY | constants.O_NOFOLLOW);
    this.configurationPath = join(config.directory, `${this.socketName}.json`);
    this.command = [config.node_executable, join(config.directory, "client.mjs"), this.configurationPath];
    this.server = createServer({ maxHeaderSize: 2048 }, (req, res) => { void this.handle(req, res); });
    this.server.requestTimeout = 15000; this.server.headersTimeout = 5000; this.server.keepAliveTimeout = 1000;
    this.server.maxConnections = 8;
    this.server.on("clientError", (_error, socket) => socket.destroy());
  }

  async start(): Promise<void> {
    requireThat(!this.started && !this.closed, "native_agent_broker_already_started"); this.started = true;
    try {
      this.check(false);
      await new Promise<void>((resolve, reject) => {
        this.server.once("error", reject);
        this.server.listen(join(`/proc/self/fd/${this.directoryFd}`, this.socketName), () => { this.server.off("error", reject); resolve(); });
      });
      const socket = lstatSync(join(this.config.directory, this.socketName)); this.socketIdentity = { dev: socket.dev, ino: socket.ino };
      chmodSync(join(this.config.directory, this.socketName), 0o600);
      writeFileSync(this.configurationPath, canonical({ schema_version: "controlmesh.native_agent_client.v1", socket_name: this.socketName,
        token: this.token, peer_tasks: this.scope.peer_tasks, ...(this.config.tool_profile ? { tool_profile: this.config.tool_profile } : {}) }), { mode: 0o600, flag: "wx" });
      const file = lstatSync(this.configurationPath); this.configurationIdentity = { dev: file.dev, ino: file.ino };
    } catch (error) { await this.close(); throw error; }
  }

  private check(dispatched = true): void {
    requireThat(!this.closed, "native_agent_broker_closed");
    this.assertCurrent();
    requireThat(assertNativeAgentConfiguration(this.config) === this.identity, "native_agent_profile_changed");
    if (dispatched) this.backend.assertDispatched();
  }

  private async handle(req: IncomingMessage, res: ServerResponse): Promise<void> {
    const respond = (status: number, value: Record<string, unknown>) => {
      if (!res.destroyed && !res.writableEnded) { res.writeHead(status, { "content-type": "application/json", "cache-control": "no-store" }); res.end(canonical(value)); }
    };
    try {
      requireThat(req.method === "POST" && req.url === "/call" && !req.headers.origin && !req.headers["sec-fetch-site"], "native_agent_request_refused");
      const authorization = req.headers.authorization, expected = `Bearer ${this.token}`;
      requireThat(typeof authorization === "string" && Buffer.byteLength(authorization) === Buffer.byteLength(expected)
        && timingSafeEqual(Buffer.from(authorization), Buffer.from(expected)), "native_agent_auth_required");
      this.check();
      let bytes = Buffer.alloc(0);
      for await (const chunk of req) { bytes = Buffer.concat([bytes, chunk]); requireThat(bytes.length <= 17000, "native_agent_request_too_large"); }
      this.check();
      const value: unknown = JSON.parse(bytes.toString("utf8"));
      requireThat(object(value) && Object.keys(value).length === 2 && typeof value.tool === "string" && object(value.input), "invalid_native_agent_request");
      const input = value.input, tool = value.tool;
      identifier(input.request_id);
      const key = input.request_id, hash = digest({ tool, input }), prior = this.active.get(key);
      if (prior) {
        requireThat(prior.digest === hash, "idempotency_conflict");
        const response = await prior.promise; this.check(); respond(200, response); return;
      }
      requireThat(this.active.size < 4, "native_agent_concurrency_exhausted");
      const promise = this.backend.call(tool, input, this.abort.signal);
      this.active.set(key, { digest: hash, promise });
      try { const response = await promise; this.check(); respond(200, response); }
      finally { this.active.delete(key); }
    } catch (error) {
      respond(409, { ok: false, error: error instanceof RuntimeConflict ? error.code : "native_agent_request_failed" });
    }
  }

  /** Stop admission before comparing native tool evidence; no late call can follow acceptance. */
  async close(): Promise<void> {
    if (this.closed) return; this.closed = true; this.abort.abort();
    await Promise.allSettled([...this.active.values()].map(value => value.promise));
    this.server.closeAllConnections();
    await new Promise<void>(resolve => this.server.close(() => resolve()));
    const removeOwned = (path: string, identity: { dev: number; ino: number } | undefined) => {
      if (!identity) return;
      try { const stat = lstatSync(path); if (stat.dev === identity.dev && stat.ino === identity.ino) unlinkSync(path); }
      catch (error) { if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error; }
    };
    try { removeOwned(join(this.config.directory, this.socketName), this.socketIdentity); removeOwned(this.configurationPath, this.configurationIdentity); }
    finally { closeSync(this.directoryFd); }
  }
}

/** The same private native IPC serves a local kernel or an authenticated remote owner. */
export class NativeAgentBroker extends NativeAgentChannel {
  constructor(kernel: RuntimeKernel, actor: Principal, lease: Lease, effect: string,
    config: NativeAgentConfiguration, assertCurrent: () => void) {
    requireThat(config.tool_profile === undefined, "message_broker_requires_message_profile");
    const journal = new NativeAgentJournal(kernel), scope = nativeAgentScope(config, lease);
    const identity = assertNativeAgentConfiguration(config);
    const current = () => {
      assertCurrent(); requireThat(assertNativeAgentConfiguration(config) === identity, "native_agent_profile_changed");
      journal.assertExecution(actor, lease, effect, scope);
    };
    super(lease, config, assertCurrent, { assertDispatched: current, call: async (tool, input, signal) => {
      current();
      const begun = journal.begin(actor, lease, effect, scope, tool, input);
      if (begun.response) return begun.response;
      const wait = tool === "controlmesh_receive" && Number.isSafeInteger(input.wait_ms) && Number(input.wait_ms) <= 10000 ? Number(input.wait_ms) : 0;
      const deadline = performance.now() + Math.max(0, wait);
      while (performance.now() < deadline && !journal.available(actor, lease)) {
        current(); signal.throwIfAborted();
        await delay(Math.min(100, Math.max(1, deadline - performance.now())), undefined, { signal });
      }
      current(); signal.throwIfAborted();
      return journal.finish(actor, lease, effect, scope, begun.call_id);
    } });
  }
}
