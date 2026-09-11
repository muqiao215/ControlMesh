import type { DeliveryContext } from "./delivery-outbox";
import { identifier, object, requireThat, RuntimeConflict } from "./value";

export interface FeishuAppCredential { app_id: string; app_secret: string; revision: string }
export interface FeishuCredentialConfiguration {
  app_id: string;
  domain?: "https://open.feishu.cn" | "https://open.larksuite.com";
  load(): FeishuAppCredential;
  assertCurrent(): void;
}
interface Token { value: string; until: number }
interface Refresh { revision: string; controller: AbortController; result: Promise<Token>; waiters: number }

/** One selected self-built app. Tokens stay in memory; a caller never selects credentials. */
export class FeishuTenantCredentials {
  private readonly domain: string;
  private revision: string | undefined;
  private token: Token | undefined;
  private failure: { reason: string; until: number } | undefined;
  private refresh: Refresh | undefined;
  private readonly active = new Set<Refresh>();
  private stopped = false;
  constructor(private readonly config: FeishuCredentialConfiguration, private readonly request: typeof fetch = fetch,
    private readonly now: () => number = () => performance.now(), private readonly timeoutMs = 10_000) {
    identifier(config.app_id);
    this.domain = config.domain ?? "https://open.feishu.cn";
    requireThat(["https://open.feishu.cn", "https://open.larksuite.com"].includes(this.domain), "untrusted_feishu_endpoint");
    requireThat(Number.isSafeInteger(timeoutMs) && timeoutMs >= 100 && timeoutMs <= 30_000, "invalid_feishu_auth_timeout");
  }
  private current(): FeishuAppCredential {
    requireThat(!this.stopped, "feishu_credentials_stopping");
    const checked: unknown = this.config.assertCurrent();
    if (checked !== undefined) { void Promise.resolve(checked).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
    const credential = this.config.load();
    requireThat(credential.app_id === this.config.app_id && typeof credential.app_secret === "string"
      && /^[A-Za-z0-9_.~+/=-]{1,4096}$/.test(credential.app_secret) && /^[a-f0-9]{64}$/.test(credential.revision), "feishu_app_credentials_unavailable");
    if (credential.revision !== this.revision) {
      this.refresh?.controller.abort(); this.refresh = undefined;
      this.revision = credential.revision; this.token = undefined; this.failure = undefined;
    }
    return credential;
  }
  /** Called only by an explicit blocked-delivery retry, not a scheduler or an API-error resend. */
  retry(): void { this.current(); this.failure = undefined; }
  assertToken(value: string): void {
    this.current();
    requireThat(this.token?.value === value && this.token.until > this.now(), "feishu_token_unavailable");
  }
  async stop(): Promise<void> {
    this.stopped = true; this.token = undefined;
    const active = [...this.active];
    for (const refresh of active) refresh.controller.abort();
    await Promise.all(active.map(refresh => refresh.result.catch(() => {})));
  }
  private async mint(credential: FeishuAppCredential, control: AbortController): Promise<Token> {
    let timedOut = false;
    const started = this.now(), timeout = setTimeout(() => { timedOut = true; control.abort(); }, this.timeoutMs);
    const check = () => {
      requireThat(!control.signal.aborted, "feishu_auth_interrupted");
      requireThat(this.current().revision === credential.revision, "feishu_app_credentials_changed");
    };
    const timer = setInterval(() => { try { check(); } catch { control.abort(); } }, 50);
    try {
      check();
      const response = await this.request(`${this.domain}/open-apis/auth/v3/tenant_access_token/internal`, {
        method: "POST", redirect: "error", signal: control.signal, headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ app_id: credential.app_id, app_secret: credential.app_secret }),
      });
      if (!response.ok) {
        await response.body?.cancel();
        throw new RuntimeConflict([400, 401, 403].includes(response.status) ? "feishu_auth_rejected" : "feishu_auth_unavailable");
      }
      requireThat(response.body, "feishu_auth_unavailable");
      const reader = response.body.getReader(), chunks: Uint8Array[] = []; let size = 0;
      try {
        while (true) { const chunk = await reader.read(); if (chunk.done) break;
          size += chunk.value.byteLength; requireThat(size <= 16 * 1024, "feishu_auth_response_invalid"); chunks.push(chunk.value); }
      } finally { await reader.cancel(); reader.releaseLock(); }
      check();
      const body: unknown = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(Buffer.concat(chunks)));
      requireThat(object(body) && body.code === 0, "feishu_auth_rejected");
      requireThat(typeof body.tenant_access_token === "string" && /^[A-Za-z0-9_.~+/=-]{1,4096}$/.test(body.tenant_access_token)
        && Number.isSafeInteger(body.expire) && Number(body.expire) > 0 && Number(body.expire) <= 86_400, "feishu_auth_response_invalid");
      const lifetime = Number(body.expire) * 1000;
      // Count from request start, on a monotonic clock; short-lived tokens never gain a minimum TTL.
      const until = started + lifetime - Math.min(60_000, lifetime / 10);
      requireThat(until > this.now(), "feishu_auth_response_expired");
      return { value: body.tenant_access_token, until };
    } catch (error) {
      throw new RuntimeConflict(timedOut ? "feishu_auth_timeout" : error instanceof RuntimeConflict ? error.code
        : control.signal.aborted ? "feishu_auth_interrupted" : "feishu_auth_unavailable");
    } finally { clearTimeout(timeout); clearInterval(timer); }
  }
  async get(context: DeliveryContext): Promise<string> {
    context.assertCurrent(); requireThat(!context.signal.aborted, "feishu_auth_interrupted");
    const credential = this.current();
    if (this.token && this.token.until > this.now()) return this.token.value;
    if (this.failure && this.failure.until > this.now()) throw new RuntimeConflict(this.failure.reason);
    let active = this.refresh;
    if (!active) {
      active = { revision: credential.revision, controller: new AbortController(), waiters: 0, result: undefined! };
      const owned = active; this.refresh = owned; this.active.add(owned);
      owned.result = this.mint(credential, owned.controller).then(token => {
        requireThat(this.current().revision === owned.revision && !owned.controller.signal.aborted, "feishu_app_credentials_changed");
        this.token = token; this.failure = undefined; return token;
      }).catch(error => {
        const reason = error instanceof RuntimeConflict ? error.code : "feishu_auth_unavailable";
        if (this.revision === owned.revision && (!owned.controller.signal.aborted || reason === "feishu_auth_timeout"))
          this.failure = { reason, until: reason === "feishu_auth_rejected" ? Infinity : this.now() + 30_000 };
        throw new RuntimeConflict(reason);
      }).finally(() => { this.active.delete(owned); if (this.refresh === owned) this.refresh = undefined; });
    }
    const owned = active; owned.waiters++;
    try {
      const token = await new Promise<Token>((resolve, reject) => {
        const abort = () => reject(new RuntimeConflict("feishu_auth_interrupted"));
        context.signal.addEventListener("abort", abort, { once: true });
        owned.result.then(resolve, reject).finally(() => context.signal.removeEventListener("abort", abort));
        if (context.signal.aborted) abort();
      });
      context.assertCurrent(); requireThat(!context.signal.aborted && this.current().revision === credential.revision
        && token.until > this.now(), "feishu_auth_interrupted");
      return token.value;
    } finally { if (--owned.waiters === 0 && this.refresh === owned) owned.controller.abort(); }
  }
}
