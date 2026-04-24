import { afterAll, describe, expect, mock, test } from "bun:test";

import { startHookServer } from "../src/hooks-server";
import { TargetRegistry } from "../src/target-registry";

const servers: Array<ReturnType<typeof Bun.serve>> = [];

afterAll(() => {
  for (const server of servers) {
    server.stop(true);
  }
});

describe("hook server", () => {
  test("resolves chatId/threadId payloads to QQ targets", async () => {
    const registry = await TargetRegistry.create(`/tmp/controlmesh-qqbot-targets-${Date.now()}.json`);
    registry.remember({
      scene: "group",
      chatId: 54321,
      threadId: 12345,
      userId: "12345",
      groupId: "54321",
    });

    const sendMessage = mock(async () => {});
    const client = {
      sendMessage,
      uploadFile: mock(async () => {}),
    };
    const server = startHookServer(client as never, registry, {
      host: "127.0.0.1",
      port: 0,
      token: "secret",
    });
    servers.push(server);

    const response = await fetch(`http://127.0.0.1:${server.port}/task-question`, {
      method: "POST",
      headers: {
        Authorization: "Bearer secret",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        taskId: "t1",
        question: "Need a date",
        promptPreview: "Find flights",
        chatId: 54321,
        threadId: 12345,
      }),
    });

    expect(response.status).toBe(200);
    expect(sendMessage).toHaveBeenCalledWith({
      scene: "group",
      groupId: "54321",
      userId: "12345",
      text: "Task t1 has a question:\nNeed a date\n\nFind flights",
    });
  });

  test("refuses ambiguous chatId-only group notify instead of widening delivery", async () => {
    const registry = await TargetRegistry.create(`/tmp/controlmesh-qqbot-targets-${Date.now()}-ambiguous.json`);
    registry.remember({
      scene: "group",
      chatId: 54321,
      threadId: 111,
      userId: "111",
      groupId: "54321",
    });
    registry.remember({
      scene: "group",
      chatId: 54321,
      threadId: 222,
      userId: "222",
      groupId: "54321",
    });

    const sendMessage = mock(async () => {});
    const client = {
      sendMessage,
      uploadFile: mock(async () => {}),
    };
    const server = startHookServer(client as never, registry, {
      host: "127.0.0.1",
      port: 0,
      token: "secret",
    });
    servers.push(server);

    const response = await fetch(`http://127.0.0.1:${server.port}/notify`, {
      method: "POST",
      headers: {
        Authorization: "Bearer secret",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        chatId: 54321,
        text: "status",
      }),
    });

    expect(response.status).toBe(409);
    expect(sendMessage).not.toHaveBeenCalled();
    await expect(response.json()).resolves.toEqual({
      ok: false,
      error: "Ambiguous QQ group target for chatId=54321; explicit threadId/userId is required",
    });
  });
});
