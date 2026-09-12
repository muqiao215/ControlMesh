#!/usr/bin/env bun
import { startLocalRuntimeService } from "../src/local-runtime-service";
import { parseRuntimeCli, renderRuntimeReply, resolveRuntimeNew, runtimeHelp } from "../src/runtime-cli";
import { requestRuntimeControl } from "../src/runtime-control-socket";
import { digest, object, requireThat, RuntimeConflict } from "../src/value";

let requestId: unknown;
try {
  const command = parseRuntimeCli(process.argv.slice(2));
  if (!command) console.log(runtimeHelp);
  else if (command.command === "serve") {
    let wake!: () => void;
    const stopped = new Promise<void>(resolve => { wake = resolve; });
    process.once("SIGINT", wake); process.once("SIGTERM", wake);
    const service = await startLocalRuntimeService(command.config!, command.socket);
    try {
      console.log(JSON.stringify({ status: "listening", socket: service.socket, pid: process.pid }));
      await Promise.race([stopped, service.failure]);
    } finally { process.off("SIGINT", wake); process.off("SIGTERM", wake); await service.close(); }
  } else {
    requestId = command.request!.id;
    if (command.command === "new") {
      const profile = await requestRuntimeControl(command.socket, { id: digest([requestId, "configuration"]), op: "status" }, command.timeout_ms)
        .catch(() => { throw new RuntimeConflict("cli_configuration_unavailable"); });
      requireThat(profile.ok && object(profile.result), "cli_configuration_unavailable");
      command.request = resolveRuntimeNew(command.request!, profile.result.configuration);
    }
    const reply = await requestRuntimeControl(command.socket, command.request!, command.timeout_ms);
    console.log(renderRuntimeReply(reply, command.json)); if (!reply.ok) process.exitCode = 1;
  }
} catch (error) {
  console.error(JSON.stringify({ error: error instanceof RuntimeConflict ? error.code : "local_runtime_command_failed", ...(requestId ? { request_id: requestId } : {}) }));
  process.exitCode = 2;
}
