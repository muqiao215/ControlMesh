import { describe, expect, test } from "bun:test";

import {
  buildFileUploadAction,
  buildSendAction,
  normalizeMessageEvent,
  renderControlMeshResult,
} from "../src/onebot";

describe("onebot normalization", () => {
  test("normalizes group messages with media markers", () => {
    expect(
      normalizeMessageEvent({
        post_type: "message",
        message_type: "group",
        group_id: 54321,
        user_id: 12345,
        message_id: 7,
        message: [
          { type: "text", data: { text: "hello" } },
          { type: "image", data: { file: "cat.png" } },
          { type: "file", data: { name: "spec.pdf" } },
        ],
      }),
    ).toEqual({
      scene: "group",
      userId: "12345",
      groupId: "54321",
      messageId: "7",
      text: "hello\n[IMAGE] cat.png\n[FILE] spec.pdf",
    });
  });

  test("builds group send action with @mention for per-user isolation", () => {
    expect(
      buildSendAction({
        scene: "group",
        userId: "12345",
        groupId: "54321",
        text: "done",
      }),
    ).toEqual({
      action: "send_group_msg",
      params: {
        group_id: 54321,
        message: [
          { type: "at", data: { qq: 12345 } },
          { type: "text", data: { text: " done" } },
        ],
      },
    });
  });

  test("builds private file upload action", () => {
    expect(
      buildFileUploadAction({
        scene: "private",
        userId: "12345",
        filePath: "/tmp/report.md",
        name: "report.md",
      }),
    ).toEqual({
      action: "upload_private_file",
      params: {
        user_id: 12345,
        file: "/tmp/report.md",
        name: "report.md",
      },
    });
  });

  test("renders attachment path hints in outgoing text", () => {
    expect(
      renderControlMeshResult("Report ready", [{ name: "report.md", path: "/tmp/report.md" }]),
    ).toBe("Report ready\n\n[ATTACHMENT] report.md: /tmp/report.md");
  });
});
