import { claudeControlCommand, ClaudeControlSession, validateClaudeControlInput } from "./claude-control";
import { digest, requireThat } from "../value";

// This helper and its native child remain inside ProcessSupervisor's anchored process group.
// Native records are wrapped so a provider cannot forge the helper's input/exit observations.
const emit = (value: Record<string, unknown>) => process.stdout.write(JSON.stringify({ type: "controlmesh.claude_control", ...value }) + "\n");
let active: { binding: string; machine: ClaudeControlSession } | undefined;
const abort = (reason: string): never => {
  if (active) emit({ event: "aborted", input_digest: active.binding, input_attempted: active.machine.inputAttempted, reason });
  process.stderr.write(reason + "\n"); process.exit(2);
};
try {
  let bytes = Buffer.alloc(0);
  for await (const chunk of Bun.stdin.stream()) {
    bytes = Buffer.concat([bytes, Buffer.from(chunk)]); requireThat(bytes.length <= 65536, "claude_control_input_limit");
  }
  const input: unknown = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
  validateClaudeControlInput(input);
  requireThat(process.cwd() === input.workspace, "claude_control_workspace_mismatch");
  const binding = digest(input), machine = new ClaudeControlSession(input);
  const child = Bun.spawn(claudeControlCommand(input), { cwd: input.workspace, env: process.env, stdin: "pipe", stdout: "pipe", stderr: "inherit" });
  emit({ event: "started", input_digest: binding });
  active = { binding, machine };
  const timer = setTimeout(() => abort("claude_control_admission_timeout"), 15000);
  const send = async (frames: Record<string, unknown>[]) => {
    for (const frame of frames) {
      if (frame.type === "user") { emit({ event: "input_attempted", input_digest: binding }); clearTimeout(timer); }
      child.stdin.write(JSON.stringify(frame) + "\n"); await child.stdin.flush();
    }
  };
  await send(machine.start().frames);
  let pending = Buffer.alloc(0), total = 0;
  for await (const chunk of child.stdout) {
    total += chunk.length; requireThat(total <= 4 * 1024 * 1024, "claude_control_output_limit");
    pending = Buffer.concat([pending, Buffer.from(chunk)]);
    let end: number;
    while ((end = pending.indexOf(10)) >= 0) {
      const line = pending.subarray(0, end); pending = pending.subarray(end + 1);
      requireThat(line.length > 0 && line.length <= 512 * 1024, "claude_control_record_limit");
      const row: unknown = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(line));
      emit({ event: "native", row });
      const action = machine.accept(row);
      if (action.delay_ms) await Bun.sleep(action.delay_ms);
      await send(action.frames);
      if (machine.complete) child.stdin.end();
    }
    requireThat(pending.length <= 512 * 1024, "claude_control_record_limit");
  }
  requireThat(pending.length === 0, "claude_control_partial_record");
  const code = await child.exited; clearTimeout(timer);
  emit({ event: "exited", exit_code: code });
  process.exitCode = machine.complete ? 0 : 2;
} catch (error) {
  // Exiting this owned helper lets its supervisor reap the entire anchored native process tree.
  abort(error instanceof Error && /^[a-z0-9_]{1,96}$/.test(error.message) ? error.message : "claude_control_process_failed");
}
