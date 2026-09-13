import { TelegramTextDelivery } from "./telegram-delivery";
import { privateFile } from "./private-runtime-file";
import { decodeSnapshot } from "./migration";
import { object, requireThat } from "./value";

/** Selected bot credentials remain private and are checked at each delivery boundary. */
export function openTelegramDelivery(profile: unknown, transport: string, current: () => void, request: typeof fetch = fetch) {
  requireThat(object(profile) && profile.kind === "telegram_text" && transport === "telegram"
    && typeof profile.adapter_id === "string" && typeof profile.bot_id === "string" && typeof profile.credentials_file === "string"
    && Object.keys(profile).every(key => ["kind", "adapter_id", "bot_id", "credentials_file"].includes(key)), "invalid_telegram_delivery_profile");
  const botId = profile.bot_id, path = profile.credentials_file;
  let revision: string | undefined;
  const load = () => {
    current(); const loaded = privateFile(path), data = decodeSnapshot(loaded.bytes).source;
    requireThat(object(data) && data.bot_id === botId && typeof data.bot_token === "string", "telegram_credentials_unavailable");
    requireThat(revision === undefined || revision === loaded.revision, "telegram_credentials_changed");
    revision ??= loaded.revision;
    return data.bot_token;
  };
  // Pin the first qualified file for this runtime generation; rotation requires reopening.
  const adapter = new TelegramTextDelivery({ adapter_id: profile.adapter_id, bot_id: botId, assertCurrent: current,
    async botToken(context) { context.assertCurrent(); return load(); },
    assertToken(token) { requireThat(load() === token, "telegram_credentials_changed"); },
  }, request);
  return { adapter, close: async () => {} };
}
