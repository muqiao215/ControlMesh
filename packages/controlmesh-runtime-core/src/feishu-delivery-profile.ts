import { FeishuTenantCredentials } from "./feishu-credentials";
import { FeishuTextDelivery, type FeishuReplyTarget, type FeishuReplySource } from "./feishu-delivery";
import { privateFile } from "./private-runtime-file";
import { decodeSnapshot } from "./migration";
import { object, requireThat } from "./value";

/** Trusted private startup configuration, shared by the entrypoint and isolated HTTP acceptance. */
export function openFeishuDelivery(profile: unknown, transport: string, current: () => void, request: typeof fetch = fetch, replySource?: FeishuReplySource) {
  requireThat(object(profile) && profile.kind === "feishu_text" && typeof profile.adapter_id === "string"
    && typeof profile.app_id === "string" && [undefined, "https://open.feishu.cn", "https://open.larksuite.com"].includes(profile.domain as string | undefined),
    "invalid_local_delivery_profile");
  requireThat((typeof profile.token_file === "string" && profile.app_credentials_file === undefined)
    || (typeof profile.app_credentials_file === "string" && profile.token_file === undefined), "ambiguous_feishu_credentials");
  requireThat(profile.replies === undefined || object(profile.replies), "invalid_feishu_reply_profile");
  const appId = profile.app_id, domain = profile.domain as "https://open.feishu.cn" | "https://open.larksuite.com" | undefined;
  const appFile = profile.app_credentials_file, tokenFile = profile.token_file;
  const credentials = typeof appFile === "string" ? new FeishuTenantCredentials({ app_id: appId, domain, assertCurrent: current,
    load() {
      const loaded = privateFile(appFile), data = decodeSnapshot(loaded.bytes).source;
      requireThat(object(data) && data.app_id === appId && typeof data.app_secret === "string", "feishu_app_credentials_unavailable");
      return { app_id: appId, app_secret: data.app_secret, revision: loaded.revision };
    } }, request) : undefined;
  const adapter = new FeishuTextDelivery({ adapter_id: profile.adapter_id, app_id: appId, transport, domain, assertCurrent: current,
    reply_source: replySource,
    replies: profile.replies as Record<string, FeishuReplyTarget> | undefined,
    retryAuthentication: credentials ? () => credentials.retry() : undefined,
    assertAccessToken(token) {
      current();
      if (credentials) { credentials.assertToken(token); return; }
      const data = decodeSnapshot(privateFile(tokenFile as string).bytes).source;
      requireThat(object(data) && data.app_id === appId && data.tenant_access_token === token
        && Number.isSafeInteger(data.expires_at) && Number(data.expires_at) > Date.now(), "feishu_token_unavailable");
    },
    async tenantAccessToken(context) {
      if (credentials) return credentials.get(context);
      context.assertCurrent(); current();
      const data = decodeSnapshot(privateFile(tokenFile as string).bytes).source;
      requireThat(object(data) && data.app_id === appId && typeof data.tenant_access_token === "string"
        && Number.isSafeInteger(data.expires_at) && Number(data.expires_at) > Date.now(), "feishu_token_unavailable");
      return data.tenant_access_token;
    } }, request);
  return { adapter, close: async () => { await credentials?.stop(); } };
}
