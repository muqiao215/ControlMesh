import { expect, test } from "bun:test";
import { mkdtempSync, mkdirSync, realpathSync, writeFileSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { openLocalRuntime } from "../src/local-runtime-config";
import { LocalRuntimeControl } from "../src/local-runtime-control";
import { HostJobStore } from "../src/host-job-store";
import type { Principal } from "../src/kernel";

for (const recover of [false, true]) test(`configured host queue advances two explicitly approved steps, recovery=${recover}`, async () => {
  const root = mkdtempSync(join(tmpdir(), "cm-configured-host-"));
  const state = join(root, "state"), workspace = join(root, "workspace"), path = join(root, "config.json");
  mkdirSync(state, { mode: 0o700 }); mkdirSync(workspace);
  writeFileSync(path, JSON.stringify({ schema_version: "controlmesh.local_runtime.v1", mode: "candidate", state_root: state,
    principal_id: "owner", device_id: "local", source: { command_origin: "human_request", origin: "user", source_scope: "local_foreground", transport: "terminal" },
    host: { shell: realpathSync("/bin/bash") }, workspace: { directory: workspace, read_files: [], required_reads: [] } }), { mode: 0o600 });
  const actor: Principal = { id: "owner", device_id: "local", origin: "human_request", scopes: ["task:admin", "task:read"] };
  let owned = openLocalRuntime(path);
  const control = () => new LocalRuntimeControl(owned.runtime, undefined, owned.submissionIdentity, undefined, undefined, owned.recovery);
  try {
    new HostJobStore(owned.runtime.kernel.db, () => {}).put(actor, "create-job", 0, { job_id: "job", repo: workspace,
      created_at: "2026-09-13", updated_at: "2026-09-13", steps: ["one", "two"].map(id => ({ id, command: `printf '${id}\\n' >> marker`, approval_required: true })) });
    expect(owned.describe().providers).toEqual([{ provider: "host", model: "" }]);
    const outOfOrder = await control().handle({ id: "approve-out-of-order", op: "approve_host_step", job_id: "job", expected_revision: 1, step_id: "two" });
    expect(outOfOrder.ok).toBe(false);
    for (const [index, step] of ["one", "two"].entries()) {
      const revision = owned.runtime.inspectHostJob("job")!.revision;
      const approval = await control().handle({ id: `approve-${step}`, op: "approve_host_step", job_id: "job", expected_revision: revision, step_id: step });
      expect(approval.ok).toBe(true);
      const submitted = await control().handle({ id: `submit-${step}`, op: "submit", task: { task_id: step, chat_id: "test", status: "waiting", provider: "host",
        host_job: { job_id: "job", revision, step_id: step, approval: approval.result } } });
      expect(submitted.ok).toBe(true);
      const queued = await control().handle({ id: `enqueue-${step}`, op: "enqueue", task_id: step, expected_revision: 1 });
      expect(queued.ok).toBe(true);
      if (recover && index === 0) owned.runtime.kernel.db.sql.exec("CREATE TRIGGER lost_completion BEFORE UPDATE ON host_jobs WHEN NEW.revision=3 BEGIN SELECT RAISE(ABORT,'lost completion'); END;");
      await owned.runtime.drain();
      if (recover && index === 0) {
        expect(owned.runtime.inspectTask(step).needs_reconciliation).toBe(true);
        owned.runtime.kernel.db.sql.exec("DROP TRIGGER lost_completion;");
        await owned.close(); owned = openLocalRuntime(path);
        const revision = owned.runtime.inspectTask(step).revision;
        const effect = (owned.runtime.kernel.db.sql.query("SELECT effect_id FROM effects WHERE task_id=?").get(step) as { effect_id: string }).effect_id;
        const inspected = await control().handle({ id: "inspect-recovery", op: "inspect_reconciliation", task_id: step, expected_revision: revision, effect_id: effect });
        expect(inspected.ok).toBe(true);
        const result = await control().handle({ id: "accept-recovery", op: "reconcile_task", task_id: step, expected_revision: revision, candidate: inspected.result });
        expect(result.ok).toBe(true);
      }
      expect(owned.runtime.inspectTask(step).task.status).toBe("done");
      expect(readFileSync(join(workspace, "marker"), "utf8")).toBe(index === 0 ? "one\n" : "one\ntwo\n");
      if (index === 0) expect(owned.runtime.inspectHostJob("job")!.job.steps[1]!.state).toBe("pending");
    }
    expect(owned.runtime.inspectHostJob("job")!.job.state).toBe("completed");
    expect(owned.runtime.kernel.db.sql.query("SELECT COUNT(*) AS n FROM provider_checks").get()).toEqual({ n: 0 });
  } finally { await owned.close(); rmSync(root, { recursive: true, force: true }); }
});
