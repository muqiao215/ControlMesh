import { DeliveryOutbox, FeishuTextDelivery, RuntimeDatabase, RuntimeKernel, type Principal } from "../src";
import { requireThat } from "../src/value";

// Isolated fault-injection process; fixture credentials and loopback HTTP only.
const [path, endpoint] = process.argv.slice(2), target = new URL(endpoint);
requireThat(target.hostname === "127.0.0.1" && target.protocol === "http:", "fixture_endpoint_required");
const actor: Principal = { id: "owner", device_id: "controller", origin: "human_request",
  scopes: ["task:read", "delivery:read", "delivery:project", "delivery:send"] };
const db = new RuntimeDatabase(path);
try {
  const adapter = new FeishuTextDelivery({ adapter_id: "selected-app", transport: "fs", app_id: "cli_fixture", assertCurrent() {},
    async tenantAccessToken() { return "fixture_token"; } }, (async (input: string | URL | Request, init?: RequestInit) => {
      const url = new URL(String(input)); requireThat(url.origin === "https://open.feishu.cn", "unexpected_fixture_domain");
      return fetch(`${target.origin}${url.pathname}${url.search}`, init);
    }) as typeof fetch);
  await new DeliveryOutbox(new RuntimeKernel(db), actor, [adapter], () => {}, 1000).drain();
} finally { db.close(); }
