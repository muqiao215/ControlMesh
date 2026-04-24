import { describe, expect, test } from "bun:test";

import { buildSessionTarget, formatScope } from "../src/session-key";

describe("session key mapping", () => {
  test("maps private chat to chat_id only", () => {
    expect(buildSessionTarget({ scene: "private", userId: "123456" })).toEqual({
      chatId: 123456,
    });
  });

  test("maps group chat to group chat_id and user channel_id", () => {
    expect(
      buildSessionTarget({
        scene: "group",
        groupId: "999888",
        userId: "123456",
      }),
    ).toEqual({
      chatId: 999888,
      channelId: 123456,
    });
  });

  test("formats group scope as per-user independent key", () => {
    expect(
      formatScope({
        scene: "group",
        groupId: "10001",
        userId: "20002",
      }),
    ).toBe("group:10001:20002");
  });
});
