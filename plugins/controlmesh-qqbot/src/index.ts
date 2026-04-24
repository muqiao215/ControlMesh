import { handleOneBotMessage } from "./bridge";
import { loadConfig } from "./config";
import { startHookServer } from "./hooks-server";
import { OneBotClient } from "./onebot-client";
import { TargetRegistry } from "./target-registry";

async function main(): Promise<void> {
  const config = loadConfig();
  const targets = await TargetRegistry.create(config.targetsPath);
  const onebot = new OneBotClient(config.onebotWsUrl, config.onebotToken, async (event) => {
    await handleOneBotMessage(event, { config, onebot, targets });
  });

  await onebot.waitUntilOpen();
  const server = startHookServer(onebot, targets, {
    host: config.hookHost,
    port: config.hookPort,
    token: config.hookToken,
  });

  console.log(
    JSON.stringify(
      {
        plugin: "controlmesh-qqbot",
        onebot_ws_url: config.onebotWsUrl,
        controlmesh_ws_url: config.controlmeshWsUrl,
        hook_url: `http://${config.hookHost}:${server.port}`,
      },
      null,
      2,
    ),
  );
}

await main();
