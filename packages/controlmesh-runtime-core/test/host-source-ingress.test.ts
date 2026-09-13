import { expect, test } from "bun:test";
import { mkdtempSync, readFileSync, realpathSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { LocalTaskRuntime, RuntimeDatabase, RuntimeKernel, type Principal } from "../src";
import { HostJobAdapter } from "../src/host-job-adapter";
import { HostJobStore } from "../src/host-job-store";
import { HostJobApprovals } from "../src/host-job-approval";

for (const background of [false, true]) test(`host task traverses issued ingress, durable queue and actual process, background=${background}`, async () => {
  const root = mkdtempSync(join(tmpdir(), "cm-host-ingress-")), db = new RuntimeDatabase(join(root, "runtime.sqlite"));
  const actor: Principal = { id: "owner", device_id: "local", origin: background ? "internal" : "human_request",
    scopes: ["task:create", "task:read", "task:execute", "task:reconcile", "task:admin"] };
  const source = background
    ? { command_origin: "internal" as const, origin: "background" as const, source_scope: "background_task" as const, transport: "terminal" }
    : { command_origin: "human_request" as const, origin: "user" as const, source_scope: "direct_message" as const, transport: "telegram" };
  const kernel = new RuntimeKernel(db), host = new HostJobAdapter(kernel, actor, root, realpathSync("/bin/bash"), () => {});
  const runtime = new LocalTaskRuntime(kernel, actor, source, snapshot => host.prepare(snapshot), () => {}, {}, root);
  try {
    const task = { task_id: "task", chat_id: "test", status: "waiting" as const, workunit_kind: "long_shell", command: "printf once >> marker" };
    let submitted;
    if (background) {
      // Automatic routing must not manufacture a human approval for internal work.
      expect(() => runtime.submit("unapproved", task, { chat_id: "test" })).toThrow("host_job_human_approval_required");
      expect(db.sql.query("SELECT COUNT(*) AS n FROM host_jobs").get()).toEqual({ n: 0 });
      const human: Principal = { ...actor, origin: "human_request" };
      const job = new HostJobStore(db, () => {}).put(human, "plan", 0, { job_id: "job", repo: root,
        created_at: "2026-09-13", updated_at: "2026-09-13", steps: [{ id: "step", command: task.command, approval_required: true }] });
      const approval = new HostJobApprovals(db, () => {}).approve(human, "approve", "job", job.revision, "step");
      submitted = runtime.submit("approved", { ...task, provider: "host", host_job: { job_id: "job", revision: job.revision, step_id: "step", approval } }, { chat_id: "test" });
    } else submitted = runtime.submit("direct", task, { chat_id: "test" });
    expect(submitted.task.execution_context).toMatchObject({ origin: source.origin, source_scope: source.source_scope });
    const run = runtime.enqueue("execute", "task", submitted.revision); await runtime.drain();
    expect(runtime.inspectTask("task").task.status).toBe("done");
    expect(readFileSync(join(root, "marker"), "utf8")).toBe("once");
    expect(runtime.enqueue("execute", "task", submitted.revision).run_id).toBe(run.run_id);
    await runtime.drain(); expect(readFileSync(join(root, "marker"), "utf8")).toBe("once");
  } finally { await runtime.stop(); db.close(); rmSync(root, { recursive: true, force: true }); }
});
