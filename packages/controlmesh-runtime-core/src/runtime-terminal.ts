import { randomUUID } from "node:crypto";
import { BoxRenderable, TextRenderable, TextareaRenderable, ScrollBoxRenderable, type CliRenderer, type KeyEvent } from "@opentui/core";
import { renderRuntimeReply, resolveRuntimeNew, terminalText } from "./runtime-cli";
import { object, RuntimeConflict } from "./value";

export type TerminalRequest = (request: Record<string, unknown>) => Promise<Record<string, unknown>>;
const commands = ["/tasks", "/open TASK", "/new", "/model PROVIDER", "/enqueue", "/resume TEXT", "/tell TEXT", "/events", "/cancel", "/retry", "/quit"];

/** Ephemeral presentation only: task state and admission belong to the socket service. */
export function mountRuntimeTerminal(renderer: CliRenderer, request: TerminalRequest, quit: () => void) {
  let selected: string | undefined, provider: string | undefined, configuration: unknown;
  let pending: Record<string, unknown> | undefined;
  let viewMode: "task" | "events" = "task", generation = 0;
  let busy = false, closed = false, refreshing = false, menuIndex = 0, hiddenDraft: string | undefined, exitArmed = false;
  const root = new BoxRenderable(renderer, { id: "workbench", width: "100%", height: "100%", flexDirection: "column", paddingX: 1 });
  const header = new TextRenderable(renderer, { id: "context", content: "ControlMesh · 正在连接服务", height: 2, flexShrink: 0 });
  const scroll = new ScrollBoxRenderable(renderer, { id: "work", flexGrow: 1, scrollY: true, scrollX: false });
  const body = new TextRenderable(renderer, { id: "details", content: "读取当前项目与任务…", width: "100%" });
  const menu = new TextRenderable(renderer, { id: "commands", content: "", height: 0, flexShrink: 0 });
  const footer = new TextRenderable(renderer, { id: "status", content: "Enter 提交 · Alt+Enter 换行 · / 命令 · 退出后任务继续", height: 2, flexShrink: 0 });
  const input = new TextareaRenderable(renderer, { id: "composer", height: 4, flexShrink: 0,
    placeholder: "输入新任务，或 / 查看命令",
    keyBindings: [{ name: "return", action: "submit" }, { name: "return", meta: true, action: "newline" }, { name: "return", shift: true, action: "newline" }],
    onSubmit: () => { void submit(); }, onContentChange: () => { menuIndex = 0; updateMenu(); },
  });
  renderer.root.add(root); root.add(header); root.add(scroll); scroll.add(body); root.add(menu); root.add(input); root.add(footer); input.focus();
  const filtered = () => input.plainText.startsWith("/") && !input.plainText.includes(" ") && hiddenDraft !== input.plainText
    ? commands.filter(command => command.startsWith(input.plainText)) : [];
  function updateMenu() {
    const list = filtered(); menuIndex = Math.min(menuIndex, Math.max(0, list.length - 1));
    const start = Math.max(0, menuIndex - 3), rows = list.slice(start, start + 4);
    menu.height = rows.length; menu.content = rows.map((item, i) => `${start + i === menuIndex ? "›" : " "} ${item}`).join("\n");
  }
  const call = (op: string, fields: Record<string, unknown> = {}) => request({ id: randomUUID(), op, ...fields });
  function result(reply: Record<string, unknown>) {
    if (!reply.ok) throw new RuntimeConflict(typeof reply.error === "string" ? reply.error : "terminal_request_failed");
    return reply.result;
  }
  async function transmit(packet: Record<string, unknown>): Promise<Record<string, unknown>> {
    const mutating = ["submit", "enqueue", "resume", "tell", "cancel"].includes(String(packet.op));
    try {
      const reply = await request(packet);
      // A matching reply settles transport uncertainty, including explicit runtime refusal.
      if (reply.id !== packet.id || typeof reply.ok !== "boolean") throw new RuntimeConflict("local_control_response_unknown");
      if (pending?.id === packet.id) pending = undefined;
      return reply;
    } catch (error) {
      if (mutating) pending = structuredClone(packet);
      throw error;
    }
  }
  async function snapshot() {
    if (!selected) throw new RuntimeConflict("terminal_select_task_first");
    const value = result(await call("inspect_task", { task_id: selected }));
    if (!object(value) || !Number.isSafeInteger(value.revision)) throw new RuntimeConflict("terminal_invalid_snapshot");
    return value;
  }
  async function refresh() {
    if (closed || refreshing || busy) return;
    refreshing = true; const selection = selected, version = generation;
    try {
      const status = await call("status"), state = result(status);
      if (closed || busy || selection !== selected || version !== generation) return;
      configuration = object(state) ? state.configuration : undefined;
      header.content = renderRuntimeReply(status).split("\n").slice(0, 2).join("\n") + (selected ? ` · ${terminalText(selected)}` : " · 新任务") + (provider ? ` · 新任务选择 ${terminalText(provider)}` : "");
      const reply = await call(selection ? (viewMode === "events" ? "task_events" : "inspect_task") : "list_tasks", selection ? { task_id: selection } : { limit: 50 });
      if (!closed && !busy && selection === selected && version === generation) body.content = renderRuntimeReply(reply);
    } catch (error) { if (!closed) footer.content = `连接/读取失败：${terminalText(error instanceof RuntimeConflict ? error.code : "service_unavailable")}；草稿保留`; }
    finally { refreshing = false; }
  }
  async function submit() {
    if (busy || closed || !input.plainText.trim()) return;
    const draft = input.plainText, space = draft.indexOf(" "), command = draft.startsWith("/") ? draft.slice(0, space < 0 ? undefined : space) : "prompt";
    const argument = space < 0 ? "" : draft.slice(space + 1);
    busy = true; exitArmed = false; generation++;
    let lastId: unknown;
    const send = async (op: string, fields: Record<string, unknown> = {}) => {
      const packet = { id: randomUUID(), op, ...fields }; lastId = packet.id;
      footer.content = `请求 ${packet.id} · 等待服务确认`;
      const reply = await transmit(packet); if (!closed) body.content = renderRuntimeReply(reply); return result(reply);
    };
    try {
      if (command === "/quit") { quit(); return; }
      if (pending && !["/retry", "/tasks", "/open", "/events"].includes(command)) throw new RuntimeConflict("terminal_unsettled_request_use_retry");
      if (command === "/retry") {
        if (!pending) throw new RuntimeConflict("terminal_no_unsettled_request");
        const packet = pending; lastId = packet.id;
        const reply = await transmit(packet); if (!closed) body.content = renderRuntimeReply(reply); result(reply);
        const target = object(packet.task) ? packet.task.task_id : packet.task_id;
        if (typeof target === "string") { selected = target; viewMode = "task"; }
        // Settling submit/resume does not silently enqueue a later step.
        footer.content = "原请求已确认；查看当前任务后，用 /enqueue 显式开始尚未执行的回合。";
        if (input.plainText === draft) input.setText("");
        return;
      }
      if (command === "/new") { selected = undefined; viewMode = "task"; }
      else if (command === "/tasks") { selected = undefined; await send("list_tasks", { limit: 50 }); }
      else if (command === "/open") { await send("inspect_task", { task_id: argument }); selected = argument; viewMode = "task"; }
      else if (command === "/model") {
        if (!object(configuration) || !Array.isArray(configuration.providers) || !configuration.providers.some(p => object(p) && p.provider === argument)) throw new RuntimeConflict("cli_provider_not_registered");
        provider = argument;
      } else if (command === "prompt") {
        if (selected) throw new RuntimeConflict("terminal_use_resume_or_tell");
        const taskId = randomUUID();
        const resolved = resolveRuntimeNew({ op: "submit", task: { task_id: taskId, status: "waiting", chat_id: "terminal", prompt: draft, ...(provider ? { provider } : {}) } }, configuration);
        // Even if acknowledgement is lost, preserve this target instead of creating another task.
        selected = taskId;
        const created = await send("submit", { task: resolved.task });
        if (!object(created)) throw new RuntimeConflict("terminal_invalid_snapshot");
        await send("enqueue", { task_id: selected, expected_revision: created.revision });
      } else if (["/enqueue", "/cancel", "/resume"].includes(command)) {
        const current = await snapshot();
        if (command === "/resume" && !argument.trim()) throw new RuntimeConflict("empty_task_update");
        await send(command.slice(1), { task_id: selected, expected_revision: current.revision, ...(command === "/resume" ? { prompt: argument } : {}) });
      } else if (command === "/tell" || command === "/events") {
        if (!selected) throw new RuntimeConflict("terminal_select_task_first");
        if (command === "/events") viewMode = "events";
        await send(command === "/tell" ? "tell" : "task_events", { task_id: selected, ...(command === "/tell" ? { text: argument } : {}) });
      } else throw new RuntimeConflict("unknown_cli_command");
      if (!closed) {
        if (input.plainText === draft) input.setText("");
        footer.content = command === "/resume" ? "续接已确认；/enqueue 开始执行这一回合" : `已确认${lastId ? ` · ${lastId}` : ""} · Enter 提交 · / 命令`;
      }
    } catch (error) {
      if (!closed) footer.content = `未完成：${terminalText(error instanceof RuntimeConflict ? error.code : "response_unknown")} · 请求 ${terminalText(pending?.id ?? lastId)}\n草稿保留；/retry 以原 ID 确认请求，勿重复创建。`;
    } finally { busy = false; if (!closed) updateMenu(); }
  }
  async function interrupt() {
    if (busy || closed) return;
    busy = true; generation++;
    try {
      if (pending) throw new RuntimeConflict("terminal_unsettled_request_use_retry");
      if (selected) {
        const current = await snapshot();
        if (object(current.task) && ["waiting", "running"].includes(String(current.task.status))) {
          const packet = { id: randomUUID(), op: "cancel", task_id: selected, expected_revision: current.revision };
          footer.content = `正在取消当前版本 · 请求 ${packet.id}`;
          try {
            const reply = await transmit(packet); result(reply);
            if (!closed) footer.content = "取消已确认；保留任务和草稿。进程退出状态以服务端后续状态为准。";
          } catch (error) {
            if (!closed) footer.content = `取消未确认：${terminalText(error instanceof RuntimeConflict ? error.code : "response_unknown")} · ${packet.id}`;
          }
          return;
        }
      }
      if (input.plainText) { input.setText(""); exitArmed = false; }
      else if (exitArmed) quit();
      else { exitArmed = true; footer.content = "再次 Ctrl+C 退出；后台任务继续。"; }
    } catch (error) {
      if (!closed) footer.content = `无法确认任务状态：${terminalText(error instanceof RuntimeConflict ? error.code : "service_unavailable")}；/quit 可退出客户端。`;
    } finally { busy = false; }
  }
  function onKey(key: KeyEvent) {
    const list = filtered();
    if (list.length && ["up", "down", "tab", "escape", "return"].includes(key.name) && !key.meta && !key.shift) {
      key.preventDefault();
      if (key.name === "escape") hiddenDraft = input.plainText;
      else if (key.name === "up") menuIndex = (menuIndex + list.length - 1) % list.length;
      else if (key.name === "down") menuIndex = (menuIndex + 1) % list.length;
      else { const chosen = list[menuIndex]!; input.setText(chosen.includes(" ") ? chosen.slice(0, chosen.indexOf(" ") + 1) : chosen); hiddenDraft = input.plainText; }
      updateMenu(); return;
    }
    if (key.ctrl && key.name === "c") {
      key.preventDefault();
      if (busy) { footer.content = "请求仍在等待确认；不会因 Ctrl+C 重发。"; return; }
      void interrupt();
    } else exitArmed = false;
  }
  renderer.keyInput.on("keypress", onKey);
  const timer = setInterval(() => { void refresh(); }, 2000); void refresh();
  return { input, refresh, submit, interrupt, dispose() { closed = true; clearInterval(timer); renderer.keyInput.off("keypress", onKey); root.destroyRecursively(); } };
}

export async function runRuntimeTerminal(socket: string, timeoutMs: number) {
  const { createCliRenderer } = await import("@opentui/core");
  const { requestRuntimeControl } = await import("./runtime-control-socket");
  let finish!: () => void;
  const done = new Promise<void>(resolve => { finish = resolve; });
  const renderer = await createCliRenderer({ exitOnCtrlC: false, onDestroy: finish });
  const view = mountRuntimeTerminal(renderer, packet => requestRuntimeControl(socket, packet, timeoutMs), finish);
  try { await done; } finally { view.dispose(); renderer.destroy(); }
}
