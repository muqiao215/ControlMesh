import { randomUUID } from "node:crypto";
import { closeSync, constants, fstatSync, openSync, readSync } from "node:fs";
import { isAbsolute } from "node:path";
import { stripVTControlCharacters } from "node:util";
import { identifier, object, requireThat } from "./value";

export const runtimeHelp = `ControlMesh TypeScript 运行时（候选入口）
用法：cm-runtime --socket /absolute/private/runtime.sock COMMAND

  serve --config FILE             启动后台运行时服务，前台保持运行
  status                          查看队列与并发容量
  tasks [--after ID] [--limit N]   查看任务、结果状态和阻塞原因
  inspect TASK                    查看任务及当前版本
  events TASK [--after N]         查看有来源标记的任务事件
  new TASK --prompt TEXT           使用已注册项目和模型创建任务
    [--provider NAME] [--model ID] 多 Provider 时显式选择；使用 enqueue 执行
  enqueue TASK --revision N       执行已创建的任务
  resume TASK --revision N --prompt TEXT
                                  原任务续接；使用 enqueue 开始新回合
  cancel TASK --revision N        取消指定版本的任务
  tell TASK --text TEXT           向原任务发送后续信息
  request --file FILE             发送既有私有控制操作，供 Agent/脚本使用

可选：--json，--request-id ID，--timeout-ms N；--prompt-file FILE 替代 --prompt。
关闭客户端不取消后台任务。超时可能表示结果未知；保留请求 ID，先检查原任务。
此入口尚未替换已安装的 Python cm，也不代表终端产品体验已验收。`;

function commandFile(path: string): string {
  const fd = openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  try {
    const before = fstatSync(fd); requireThat(before.isFile() && before.size <= 65_536, "local_command_file_invalid");
    const bytes = Buffer.alloc(before.size + 1); let n = 0;
    while (n < bytes.length) { const read = readSync(fd, bytes, n, bytes.length - n, null); if (!read) break; n += read; }
    const after = fstatSync(fd);
    requireThat(n === before.size && before.size === after.size && before.mtimeMs === after.mtimeMs && before.ctimeMs === after.ctimeMs, "local_command_file_changed");
    return new TextDecoder("utf-8", { fatal: true }).decode(bytes.subarray(0, n));
  } finally { closeSync(fd); }
}
export interface RuntimeCliCommand {
  command: string; socket: string; json: boolean; timeout_ms: number; request?: Record<string, unknown>; config?: string;
}
export function parseRuntimeCli(argv: string[]): RuntimeCliCommand | null {
  if (argv.length === 0 || argv.includes("--help")) return null;
  const args: string[] = [], flags: Record<string, string | boolean> = {};
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i]!;
    if (!arg.startsWith("--")) { args.push(arg); continue; }
    requireThat(!Object.hasOwn(flags, arg), "duplicate_cli_option");
    if (arg === "--json") flags[arg] = true;
    else { const next = argv[++i]; requireThat(next !== undefined && !next.startsWith("--"), "missing_cli_option_value"); flags[arg] = next; }
  }
  const command = args[0]!, options: Record<string, string[]> = {
    serve: ["--config"], status: [], tasks: ["--after", "--limit"], inspect: [], events: ["--after", "--limit"],
    new: ["--project", "--provider", "--model", "--prompt", "--prompt-file"], enqueue: ["--revision"],
    resume: ["--revision", "--prompt", "--prompt-file"], cancel: ["--revision"], tell: ["--text"], request: ["--file"],
  };
  requireThat(Object.hasOwn(options, command), "unknown_cli_command");
  requireThat(Object.keys(flags).every(flag => ["--socket", "--json", "--request-id", "--timeout-ms", ...options[command]!].includes(flag)), "unknown_cli_option");
  const text = (flag: string) => { requireThat(typeof flags[flag] === "string" && String(flags[flag]).length > 0, "missing_cli_option"); return flags[flag] as string; };
  const number = (flag: string, fallback?: number) => {
    if (flags[flag] === undefined && fallback !== undefined) return fallback;
    const raw = text(flag); requireThat(/^\d+$/.test(raw) && Number.isSafeInteger(Number(raw)), "invalid_cli_number"); return Number(raw);
  };
  const socket = text("--socket"); requireThat(isAbsolute(socket), "local_socket_path_invalid");
  const timeout_ms = number("--timeout-ms", 30_000); requireThat(timeout_ms > 0 && timeout_ms <= 300_000, "invalid_local_control_timeout");
  const targeted = ["inspect", "events", "new", "enqueue", "resume", "cancel", "tell"].includes(command);
  requireThat(args.length === (targeted ? 2 : 1), "invalid_cli_arguments");
  const base = { command, socket, json: flags["--json"] === true, timeout_ms };
  if (command === "serve") { const config = text("--config"); requireThat(isAbsolute(config), "private_config_path_required"); return { ...base, config }; }
  if (targeted) identifier(args[1]);
  let request: Record<string, unknown>;
  if (command === "request") {
    const loaded: unknown = JSON.parse(commandFile(text("--file"))); requireThat(object(loaded), "invalid_local_request"); request = loaded;
    requireThat(flags["--request-id"] === undefined || loaded.id === undefined || flags["--request-id"] === loaded.id, "cli_request_id_conflict");
  } else {
    const prompt = () => { requireThat((flags["--prompt"] === undefined) !== (flags["--prompt-file"] === undefined), "cli_prompt_required");
      return flags["--prompt"] === undefined ? commandFile(text("--prompt-file")) : text("--prompt"); };
    switch (command) {
      case "status": request = { op: "status" }; break;
      case "tasks": request = { op: "list_tasks", after: flags["--after"] ?? "", limit: number("--limit", 50) }; break;
      case "inspect": request = { op: "inspect_task", task_id: args[1] }; break;
      case "events": request = { op: "task_events", task_id: args[1], after: number("--after", 0), limit: number("--limit", 50) }; break;
      case "new": {
        const project = flags["--project"] === undefined ? undefined : text("--project");
        requireThat(project === undefined || isAbsolute(project), "cli_project_required");
        request = { op: "submit", task: { task_id: args[1], status: "waiting", chat_id: "terminal", ...(project ? { repo_root: project } : {}),
          ...(flags["--provider"] ? { provider: text("--provider") } : {}), ...(flags["--model"] ? { model: text("--model") } : {}), prompt: prompt() } }; break;
      }
      case "enqueue": case "cancel": case "resume": request = { op: command, task_id: args[1], expected_revision: number("--revision"),
        ...(command === "resume" ? { prompt: prompt() } : {}) }; break;
      case "tell": request = { op: "tell", task_id: args[1], text: text("--text") }; break;
      default: throw new Error("unreachable CLI command");
    }
  }
  request.id = flags["--request-id"] ?? request.id ?? randomUUID(); identifier(request.id);
  return { ...base, request };
}

/** Resolve display defaults from the service's current registration, never from native history or guessed readiness. */
export function resolveRuntimeNew(request: Record<string, unknown>, description: unknown): Record<string, unknown> {
  requireThat(object(description) && description.mode === "candidate" && typeof description.workspace === "string"
    && Array.isArray(description.providers) && description.providers.every(item => object(item) && typeof item.provider === "string" && typeof item.model === "string"), "cli_configuration_unavailable");
  requireThat(request.op === "submit" && object(request.task), "invalid_local_request");
  const task = request.task, providers = description.providers as { provider: string; model: string }[];
  const matches = task.provider === undefined ? providers : providers.filter(item => item.provider === task.provider);
  requireThat(matches.length === 1, matches.length ? "cli_provider_selection_required" : "cli_provider_not_registered");
  const selected = matches[0]!;
  requireThat(task.model === undefined || task.model === selected.model, "cli_model_not_registered");
  requireThat(task.repo_root === undefined || task.repo_root === description.workspace, "cli_project_not_registered");
  return { ...request, task: { ...task, repo_root: description.workspace, provider: selected.provider, model: selected.model } };
}

/** Provider text is data, including OSC links, cursor movement, CR and backspace. */
export function terminalText(value: unknown): string {
  return stripVTControlCharacters(String(value ?? "")).replace(/[\u0000-\u001f\u007f-\u009f]/g, " ");
}
const printableJson = (value: unknown, space?: number) => JSON.stringify(value, null, space)?.replace(/[\u007f-\u009f]/g, c => `\\u${c.charCodeAt(0).toString(16).padStart(4, "0")}`) ?? "null";
export function renderRuntimeReply(reply: Record<string, unknown>, json = false): string {
  if (json) return printableJson(reply);
  const id = terminalText(reply.id), result = reply.result;
  if (!reply.ok) return `失败：${terminalText(reply.error)}\n请求：${id}`;
  if (object(result) && Array.isArray(result.tasks)) {
    const rows = result.tasks.filter(object).map(task => {
      const run = object(task.run) ? task.run : null, outcome = run && object(run.outcome) ? run.outcome : null;
      return [task.task_id, task.status, task.provider, task.model, outcome?.reason ?? task.title].map(terminalText).join("  ");
    });
    return ["任务  状态  Provider  模型  进展/阻塞", ...rows, ...(rows.length ? [] : ["暂无任务"]),
      ...(result.next_after ? [`下一页：--after ${terminalText(result.next_after)}`] : [])].join("\n");
  }
  if (object(result) && object(result.queue)) {
    const configuration = object(result.configuration) ? result.configuration : null;
    const registered = configuration && Array.isArray(configuration.providers) ? configuration.providers.filter(object) : [];
    return [...(configuration ? [`项目：${terminalText(configuration.workspace)}`, `已注册模型：${registered.map(item => `${terminalText(item.provider)}/${terminalText(item.model)}`).join("，")}（执行时预检）`] : []),
      `服务已连接；排队 ${terminalText(result.queue.queued)}，运行 ${terminalText(result.queue.running)}，并发容量 ${terminalText(result.parallelism)}`].join("\n");
  }
  if (object(result) && object(result.task)) return `任务 ${terminalText(result.task.task_id)}：${terminalText(result.task.status)}，版本 ${terminalText(result.revision)}${result.needs_reconciliation ? "，需要核对原执行结果" : ""}\n${printableJson(result, 2)}\n请求：${id}`;
  return `${printableJson(result, 2)}\n请求：${id}`;
}
