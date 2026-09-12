import { test, expect } from "bun:test";
import { join } from "node:path";
import { createTestRenderer } from "@opentui/core/testing";
import { mountRuntimeTerminal } from "../src/runtime-terminal";
import { object, RuntimeConflict } from "../src/value";

test("Chinese bracketed paste and resize retain draft; menu selection never submits", async () => {
  const ui = await createTestRenderer({ width: 80, height: 24 });
  const calls: Record<string, unknown>[] = [];
  const view = mountRuntimeTerminal(ui.renderer, async p => {
    calls.push(p);
    return { id: p.id, ok: true, result: p.op === "status" ? { queue: { queued: 0, running: 0 }, parallelism: 1,
      configuration: { mode: "candidate", workspace: "/project", providers: [{ provider: "claude", model: "registered" }] } } : { tasks: [] } };
  }, () => {});
  try {
    await ui.flush();
    await ui.mockInput.pasteBracketedText("你好🙂\n第二行\n第三行");
    await ui.flush();
    expect(view.input.plainText).toBe("你好🙂\n第二行\n第三行");
    ui.resize(120, 36); await ui.flush();
    expect(view.input.plainText).toBe("你好🙂\n第二行\n第三行");
    expect(ui.captureCharFrame()).toContain("第二行");
    view.input.setText("/mo"); await ui.flush();
    expect(ui.captureCharFrame()).toContain("/model PROVIDER");
    ui.mockInput.pressTab(); await ui.flush();
    expect(view.input.plainText).toBe("/model ");
    expect(calls.every(p => ["status", "list_tasks"].includes(String(p.op)))).toBe(true);
    view.input.setText("/re"); ui.mockInput.pressEscape(); await ui.flush();
    expect(view.input.plainText).toBe("/re");
  } finally { view.dispose(); ui.renderer.destroy(); }
});

test("lost submit acknowledgement preserves task and draft; Enter cannot duplicate submission", async () => {
  const ui = await createTestRenderer({ width: 120, height: 36 });
  const calls: Record<string, unknown>[] = [];
  const view = mountRuntimeTerminal(ui.renderer, async p => {
    calls.push(p);
    if (p.op === "submit") throw new RuntimeConflict("local_control_response_unknown");
    return { id: p.id, ok: true, result: p.op === "status" ? { queue: {}, configuration: { mode: "candidate", workspace: "/project", providers: [{ provider: "claude", model: "registered" }] } } : { tasks: [] } };
  }, () => {});
  try {
    await ui.flush();
    view.input.setText("执行这个任务"); await view.submit(); await ui.flush();
    expect(view.input.plainText).toBe("执行这个任务");
    expect(ui.captureCharFrame()).toContain("local_control_response_unknown");
    await view.submit();
    expect(calls.filter(p => p.op === "submit")).toHaveLength(1);
    expect(calls.filter(p => p.op === "enqueue")).toHaveLength(0);
    const task = calls.find(p => p.op === "submit")!.task;
    expect(object(task) && task.provider).toBe("claude");
  } finally { view.dispose(); ui.renderer.destroy(); }
});

test("new task enqueues only acknowledged revision; interrupt preserves the draft and uses current revision", async () => {
  const ui = await createTestRenderer({ width: 80, height: 24 });
  const calls: Record<string, unknown>[] = [];
  const view = mountRuntimeTerminal(ui.renderer, async p => {
    calls.push(p);
    let result: unknown = {};
    if (p.op === "status") result = { queue: {}, configuration: { mode: "candidate", workspace: "/project", providers: [{ provider: "claude", model: "registered" }] } };
    if (p.op === "list_tasks") result = { tasks: [] };
    if (p.op === "submit") result = { revision: 2 };
    if (p.op === "inspect_task") result = { revision: 7, task: { status: "running" } };
    return { id: p.id, ok: true, result };
  }, () => {});
  try {
    await ui.flush(); view.input.setText("开始任务"); await view.submit();
    expect(calls.find(p => p.op === "enqueue")?.expected_revision).toBe(2);
    view.input.setText("还没有提交的补充🙂"); await view.interrupt();
    expect(calls.find(p => p.op === "cancel")?.expected_revision).toBe(7);
    expect(view.input.plainText).toBe("还没有提交的补充🙂");
    expect(calls.filter(p => p.op === "submit")).toHaveLength(1);
    expect(new Set(calls.map(p => p.id)).size).toBe(calls.length);
  } finally { view.dispose(); ui.renderer.destroy(); }
});

test("non-TTY UI exits without terminal escapes or creating a service", async () => {
  const child = Bun.spawn([process.execPath, join(import.meta.dir, "../scripts/cm-runtime.ts"), "--socket", "/tmp/not-a-service.sock", "ui"], { stdout: "pipe", stderr: "pipe" });
  const [stdout, stderr, code] = await Promise.all([new Response(child.stdout).text(), new Response(child.stderr).text(), child.exited]);
  expect(code).toBe(2); expect(stdout).toBe(""); expect(stderr).toContain("terminal_tty_required"); expect(stderr).not.toContain("\x1b");
});
