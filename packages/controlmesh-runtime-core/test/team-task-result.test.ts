import { expect, test } from "bun:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { RuntimeDatabase, RuntimeKernel, readTeamTaskResult, type Principal } from "../src";
import { digest } from "../src/value";

const actor: Principal = { id: "owner", origin: "internal", device_id: "device-a", scopes: ["task:create", "task:execute", "task:read", "task:reconcile"] };
const output = { topology: "pipeline", substage: "worker_running", worker_role: "worker", status: "completed", summary: "result", evidence: [{ ref: "event:assertion" }] };

for (const recovered of [false, true]) test(`team result reads accepted task output after ${recovered ? "reconciliation" : "normal finish"} and restart`, () => {
  const root = mkdtempSync(join(tmpdir(), "cm-team-result-"));
  const path = join(root, "runtime.sqlite");
  let db = new RuntimeDatabase(path);
  try {
    let kernel = new RuntimeKernel(db);
    kernel.submit(actor, "create", { task_id: "worker", chat_id: "test", status: "waiting", provider: "opencode" });
    const lease = kernel.claim(actor, "claim", "worker", 1, 30_000);
    kernel.start(actor, "start", lease);
    kernel.dispatchEffect(actor, "dispatch", lease, "native-output", { native: true }, { retained: true });
    const text = JSON.stringify(output);
    const accepted = { text, output_digest: digest(text) };
    let done;
    if (recovered) {
      kernel.recordEffectObservation(actor, "observe", lease, "native-output", { retained: "result" });
      const stale = kernel.markUnknown(actor, "unknown", lease, "lost_confirmation");
      expect(() => readTeamTaskResult(kernel, actor, { task_id: "worker", revision: stale.revision, episode_id: lease.episode_id, effect_id: "native-output", ...output })).toThrow("task_result_not_accepted");
      const evidence = kernel.inspectReconciliation(actor, "worker", stale.revision, "native-output");
      done = kernel.reconcileEffect(actor, "reconcile", "worker", stale.revision, {
        episode_id: lease.episode_id, effect_id: "native-output", manifest_digest: evidence.manifest_digest, observation_digest: evidence.observation_digest,
      }, () => accepted);
    } else {
      kernel.confirmEffect(actor, "confirm", lease, "native-output", accepted);
      done = kernel.finish(actor, "finish", lease, "done", accepted);
    }
    db.close(); db = new RuntimeDatabase(path); kernel = new RuntimeKernel(db);
    const binding = { task_id: "worker", revision: done.revision, episode_id: lease.episode_id, effect_id: "native-output", topology: output.topology, substage: output.substage, worker_role: output.worker_role };
    const result = readTeamTaskResult(kernel, actor, binding);
    expect(result.result.summary).toBe("result");
    expect(result.output_digest).toBe(digest(text));
    expect(result.result.evidence[0]?.ref).toBe("event:assertion");
    for (const field of ["topology", "substage", "worker_role"] as const)
      expect(() => readTeamTaskResult(kernel, actor, { ...binding, [field]: "unassigned" })).toThrow("team_result_assignment_mismatch");
    const corrupt = JSON.stringify({ text, output_digest: "wrong" });
    db.sql.query("UPDATE episodes SET result=? WHERE episode_id=?").run(corrupt, lease.episode_id);
    db.sql.query("UPDATE effects SET result=? WHERE effect_id=?").run(corrupt, "native-output");
    expect(() => readTeamTaskResult(kernel, actor, binding)).toThrow("team_result_digest_mismatch");
    const prose = `Here is the result: ${text}`;
    const invalid = JSON.stringify({ text: prose, output_digest: digest(prose) });
    db.sql.query("UPDATE episodes SET result=? WHERE episode_id=?").run(invalid, lease.episode_id);
    db.sql.query("UPDATE effects SET result=? WHERE effect_id=?").run(invalid, "native-output");
    expect(() => readTeamTaskResult(kernel, actor, binding)).toThrow();
    expect(db.sql.query("SELECT COUNT(*) AS n FROM episodes").get()).toEqual({ n: 1 });
  } finally { db.close(); rmSync(root, { recursive: true, force: true }); }
});
