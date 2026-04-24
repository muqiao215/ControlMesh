import type { QqBotConfig } from "./config";
import { isAllowedUser } from "./config";
import { sendTurn } from "./controlmesh-client";
import { materializeOutboundFile } from "./outbound-files";
import type { OneBotClient } from "./onebot-client";
import type { OneBotMessageEvent } from "./onebot";
import { normalizeMessageEvent } from "./onebot";
import { buildSessionTarget } from "./session-key";
import type { TargetRegistry } from "./target-registry";

async function deliverResult(
  deps: { config: QqBotConfig; onebot: OneBotClient },
  target: { scene: "private" | "group"; userId: string; groupId?: string },
  result: Awaited<ReturnType<typeof sendTurn>>,
): Promise<void> {
  const text = result.text.trim();
  if (text) {
    await deps.onebot.sendMessage({
      scene: target.scene,
      userId: target.userId,
      groupId: target.groupId,
      text,
    });
  }

  const failures: string[] = [];
  for (const file of result.files) {
    try {
      const outbound = await materializeOutboundFile(file, deps.config);
      if (outbound.isImage) {
        await deps.onebot.sendMessage({
          scene: target.scene,
          userId: target.userId,
          groupId: target.groupId,
          text: text ? "" : outbound.name,
          imagePath: outbound.path,
        });
        continue;
      }
      await deps.onebot.uploadFile({
        scene: target.scene,
        userId: target.userId,
        groupId: target.groupId,
        filePath: outbound.path,
        name: outbound.name,
      });
    } catch (error) {
      failures.push(
        `[ATTACHMENT FAILED] ${file.name}: ${error instanceof Error ? error.message : String(error)}`,
      );
    }
  }

  if (failures.length) {
    await deps.onebot.sendMessage({
      scene: target.scene,
      userId: target.userId,
      groupId: target.groupId,
      text: failures.join("\n"),
    });
  }
}

export async function handleOneBotMessage(
  event: OneBotMessageEvent,
  deps: { config: QqBotConfig; onebot: OneBotClient; targets: TargetRegistry },
): Promise<void> {
  const normalized = normalizeMessageEvent(event);
  if (!normalized.text || !isAllowedUser(deps.config, normalized.userId)) {
    return;
  }

  const session = buildSessionTarget({
    scene: normalized.scene,
    userId: normalized.userId,
    groupId: normalized.groupId,
  });
  deps.targets.remember({
    scene: normalized.scene,
    chatId: session.chatId,
    threadId: session.channelId,
    userId: normalized.userId,
    groupId: normalized.groupId,
  });

  const result = await sendTurn({
    wsUrl: deps.config.controlmeshWsUrl,
    token: deps.config.controlmeshToken,
    chatId: session.chatId,
    channelId: session.channelId,
    transport: deps.config.controlmeshTransport,
    text: normalized.text,
  });

  await deliverResult(
    deps,
    {
      scene: normalized.scene,
      userId: normalized.userId,
      groupId: normalized.groupId,
    },
    result,
  );
}
