/** Explicit synthetic acceptance driver. Never imports provider credentials or starts production services. */
import { lstatSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { DeviceClient, DeviceWorker } from "../src";
import { digest, requireThat, RuntimeConflict } from "../src/value";

const path = process.argv[2];
const stat = lstatSync(path);
requireThat(stat.isFile() && !stat.isSymbolicLink() && (stat.mode & 0o077) === 0 && stat.uid === process.getuid!(), "private_canary_config_required");
const config = JSON.parse(readFileSync(path, "utf8"));
requireThat(["run", "claim", "start-old", "send", "receive"].includes(config.mode), "invalid_canary_mode");
const client = new DeviceClient({ endpoint: config.endpoint, token: config.token, device_id: config.device_id });
const leasePath = join(dirname(path), `${config.task_id}.lease.json`);
try {
  if (config.mode === "start-old") {
    const lease = JSON.parse(readFileSync(leasePath, "utf8"));
    await client.command("start", { lease });
    console.log(JSON.stringify({ unexpected_start: true }));
  } else if (config.mode === "claim" || config.mode === "send" || config.mode === "receive") {
    const job = await client.inspect(config.task_id);
    const authority = await client.claim(job.task_id, job.revision, job.assignment_digest, config.ttl_ms ?? 3000);
    writeFileSync(leasePath, JSON.stringify(authority.lease), { mode: 0o600 });
    if (config.mode === "claim") {
      console.log(JSON.stringify({ claimed: true, fence: authority.lease.fence, device: config.device_id }));
    } else {
      await authority.start();
      if (config.mode === "send") {
        const result = await client.command("send", { lease: authority.lease, recipient_task: config.peer_task, kind: "handoff", payload: { context_only: true, canary: "cross-device" }, causation_id: null, ttl_ms: 30000 });
        console.log(JSON.stringify({ sent: result }));
      } else {
        const messages = await client.command("messages", { lease: authority.lease }) as { message_id: string }[];
        for (const message of messages) {
          await client.command("ack", { lease: authority.lease, message_id: message.message_id, phase: "received", evidence: null });
          await client.command("ack", { lease: authority.lease, message_id: message.message_id, phase: "consumed", evidence: "synthetic cross-device payload inspected" });
        }
        console.log(JSON.stringify({ consumed: messages.length }));
      }
    }
    authority.stop();
  } else {
    let outcomeReason: string | null = null;
    const worker = new DeviceWorker(client, { workspaces: { canary: config.workspace }, adapters: { "synthetic.read": {
      async execute(context) {
        const program = 'const text = await Bun.file("PROJECT.md").text(); console.log(JSON.stringify({text})); if (process.env.CM_CANARY_HOLD === "1") { await Bun.write("canary-provider.json", JSON.stringify({pid:process.pid})); setInterval(() => {}, 50); }';
        const outcome = await context.runProcess({ command: [process.execPath, "-e", program],
          env: { CM_CANARY_HOLD: config.hold ? "1" : "0" }, timeout_ms: 15000, max_output_bytes: 4096 });
        outcomeReason = outcome.reason;
        context.assertCurrent();
        requireThat(outcome.reason === "exited" && outcome.exit_code === 0, "canary_process_unverified");
        const output = JSON.parse(outcome.stdout);
        requireThat(typeof output.text === "string" && digest(output.text) === config.expected_digest, "canary_workspace_mismatch");
        return { observation: { reason: outcome.reason, read_digest: digest(output.text) }, result: { verified_read: true, read_digest: digest(output.text), device: config.device_id } };
      },
    } } });
    const result = await worker.run(config.task_id, config.ttl_ms ?? 4000);
    console.log(JSON.stringify({ ...result, process_reason: outcomeReason, architecture: process.arch }));
  }
} catch (error) {
  console.log(JSON.stringify({ denied: error instanceof RuntimeConflict ? error.code : "canary_unverified" }));
  process.exitCode = 2;
}
