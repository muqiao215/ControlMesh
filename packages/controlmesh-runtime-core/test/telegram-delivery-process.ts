import { DeliveryOutbox, RuntimeDatabase, RuntimeKernel, type Principal } from "../src";
import { TelegramTextDelivery } from "../src/telegram-delivery";

const [path, endpoint] = process.argv.slice(2);
if (!path || !endpoint || new URL(endpoint).hostname !== "127.0.0.1") throw new Error("fixture_arguments_required");
const actor: Principal = { id: "owner", device_id: "controller", origin: "human_request",
  scopes: ["task:read", "delivery:read", "delivery:project", "delivery:send"] };
const db = new RuntimeDatabase(path);
const adapter = new TelegramTextDelivery({ adapter_id: "telegram-selected", bot_id: "123456", assertCurrent() {}, assertToken() {},
  async botToken() { return "123456:fixture_credential_only"; } }, (async (url, init) => {
  const target = new URL(String(url));
  if (target.origin !== "https://api.telegram.org") throw new Error("fixture_endpoint_unexpected");
  return fetch(`${endpoint}${target.pathname}`, init);
}) as typeof fetch);
const outbox = new DeliveryOutbox(new RuntimeKernel(db), actor, [adapter], () => {}, 1000);
try { await outbox.drain(); } finally { await outbox.stop(); db.close(); }
