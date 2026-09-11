import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { once } from "node:events";

export interface McpResponse { result?: { tools?: { name: string }[]; content?: { type: string; text: string }[] }; error?: { code: number; message: string } }
/** Actual Node stdio client process, used without a model in transport/owner tests. */
export class NativeMcpTestClient {
  private readonly child: ChildProcessWithoutNullStreams;
  private nextId = 0;
  private readonly pending = new Map<number, { resolve: (value: McpResponse) => void; reject: (error: Error) => void; timer: ReturnType<typeof setTimeout> }>();
  constructor(command: readonly string[]) {
    this.child = spawn(command[0], command.slice(1), { stdio: "pipe" });
    this.child.stderr.resume();
    this.child.stdout.setEncoding("utf8"); let input = "";
    this.child.stdout.on("data", chunk => {
      input += chunk;
      let index: number;
      while ((index = input.indexOf("\n")) >= 0) {
        const line = input.slice(0, index); input = input.slice(index + 1);
        const value = JSON.parse(line), waiting = this.pending.get(value.id);
        if (waiting) { clearTimeout(waiting.timer); this.pending.delete(value.id); waiting.resolve(value); }
      }
    });
    const fail = () => { for (const item of this.pending.values()) { clearTimeout(item.timer); item.reject(new Error("mcp_client_closed")); } this.pending.clear(); };
    this.child.on("exit", fail); this.child.on("error", fail);
  }
  request(method: string, params: Record<string, unknown> = {}): Promise<McpResponse> {
    const id = ++this.nextId;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { this.pending.delete(id); reject(new Error("mcp_test_timeout")); }, 16000);
      this.pending.set(id, { resolve, reject, timer });
      this.child.stdin.write(JSON.stringify({ jsonrpc: "2.0", id, method, params }) + "\n");
    });
  }
  initialize() { return this.request("initialize", { protocolVersion: "2025-11-25", capabilities: {}, clientInfo: { name: "cm-test", version: "1" } }); }
  tool(name: string, args: Record<string, unknown>) { return this.request("tools/call", { name, arguments: args }); }
  async close(): Promise<void> {
    if (this.child.exitCode !== null || this.child.signalCode !== null) return;
    const exited = once(this.child, "exit"); this.child.stdin.end();
    const timer = setTimeout(() => this.child.kill("SIGTERM"), 500);
    try { await exited; } finally { clearTimeout(timer); }
  }
}
