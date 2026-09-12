import { expect, test } from "bun:test";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { RuntimeDatabase, RuntimeKernel, RuntimeTopology, RuntimePipeline, LocalTaskRuntime, type Principal, type LocalTaskResolver } from "../src";
import { digest } from "../src/value";
const actor: Principal = { id: "owner", device_id: "local", origin: "internal", scopes: ["task:create", "task:read", "task:execute", "task:resume", "task:reconcile", "task:admin", "team:write"] };
const source = { command_origin: "internal" as const, origin: "background" as const, source_scope: "background_task" as const, transport: "terminal" };

for (const decision of ["needs_repair", "needs_parent_input"]) test(`pipeline queues and resumes actual local tasks for ${decision} without duplicate execution`, async () => {
  const root = mkdtempSync(join(tmpdir(), "cm-pipeline-")), db = new RuntimeDatabase(join(root, "state.sqlite")), kernel = new RuntimeKernel(db);
  const calls: string[] = [];
  const resolver: LocalTaskResolver = task => ({ binding_digest: digest("fixture"), assertCurrent() {},
    async ensureReady() { return { decision: "cached", reason: "ready", retry_after: null, report: null, permit: null }; },
    async execute(lease, context) {
      const id = task.task.task_id, prompt = String(task.task.prompt); calls.push(`${id}:${prompt}`);
      kernel.start(actor, `start-${lease.episode_id}`, lease);
      kernel.dispatchEffect(actor, `dispatch-${lease.episode_id}`, lease, lease.episode_id, { synthetic: true });
      context.assertCurrent();
      const status = id === "reviewer" && prompt === "initial" ? decision : "completed";
      const text = JSON.stringify({ topology: "pipeline", substage: id === "reviewer" ? "review_running" : prompt === "repair" ? "repairing" : "worker_running",
        worker_role: id, status, summary: `${id} output`, evidence: id === "worker" ? [{ ref: `event:${prompt}` }] : [],
        needs_parent_input: status === "needs_parent_input", repair_hint: status === "needs_repair" ? "correct output" : null });
      const result = { text, output_digest: digest(text), native_session: { session_id: `ses_synthetic_${id}` } };
      kernel.confirmEffect(actor, `confirm-${lease.episode_id}`, lease, lease.episode_id, result);
      return kernel.finish(actor, `finish-${lease.episode_id}`, lease, "done", result);
    } });
  const runtime = new LocalTaskRuntime(kernel, actor, source, resolver, () => {}), topology = new RuntimeTopology(kernel), pipeline = new RuntimePipeline(kernel, runtime);
  const child = (id: string, resume_prompt?: string) => ({ task_id: id, revision: kernel.inspect(actor, id).revision, role: id, ...(resume_prompt ? { resume_prompt } : {}) });
  try {
    for (const id of ["parent", "worker", "reviewer"]) runtime.submit(`submit-${id}`, { task_id: id, chat_id: "test", status: "waiting", provider: "opencode", prompt: "initial" }, { chat_id: "test" });
    topology.create(actor, "create-topology", "parent", 1, "pipeline", { active_roles: ["planner"], latest_summary: "plan" });
    const dispatched = pipeline.dispatch(actor, "dispatch", "parent", 1, 1, child("worker"));
    await runtime.drain();
    expect(() => pipeline.advance(actor, "advance-worker", "parent", 1, dispatched.topology.revision, "worker", child("worker").revision)).toThrow("pipeline_next_child_required");
    expect(topology.inspect(actor, "parent")).toEqual(dispatched.topology);
    expect(db.sql.query("SELECT accepted FROM topology_tasks WHERE child_id='worker'").get()).toEqual({ accepted: null });
    const review = pipeline.advance(actor, "advance-worker", "parent", 1, dispatched.topology.revision, "worker", child("worker").revision, {}, child("reviewer"));
    await runtime.drain();
    const reviewerRevision = child("reviewer").revision;
    let state;
    if (decision === "needs_repair") {
      const repair = pipeline.advance(actor, "review-decision", "parent", 1, review.topology.revision, "reviewer", reviewerRevision, {}, child("worker", "repair"));
      await runtime.drain();
      state = pipeline.advance(actor, "repair-result", "parent", 1, repair.topology.revision, "worker", child("worker").revision, {}, child("reviewer", "final"));
    } else {
      const waiting = pipeline.advance(actor, "review-decision", "parent", 1, review.topology.revision, "reviewer", reviewerRevision, { parent_question: "choose", waiting_on: "user" });
      expect(waiting.next_run).toBeNull(); expect(waiting.topology.state.interruption.status).toBe("waiting_parent");
      state = pipeline.resume(actor, "parent-answer", "parent", 1, waiting.topology.revision, "approved answer", child("reviewer", "final"));
    }
    await runtime.drain();
    const finalRevision = child("reviewer").revision;
    const final = pipeline.advance(actor, "final", "parent", 1, state.topology.revision, "reviewer", finalRevision);
    expect(final.topology.state.checkpoints.at(-1)!.substage).toBe("completed"); expect(final.next_run).toBeNull(); expect(final.parent?.task.status).toBe("done");
    expect(final.topology.state.checkpoints.at(-1)!.reduced_result!.selected_evidence[0]!.ref).toBe(decision === "needs_repair" ? "event:repair" : "event:initial");
    expect(pipeline.advance(actor, "final", "parent", 1, state.topology.revision, "reviewer", finalRevision)).toEqual(final);
    await runtime.drain();
    expect(calls).toEqual(decision === "needs_repair" ? ["worker:initial", "reviewer:initial", "worker:repair", "reviewer:final"] : ["worker:initial", "reviewer:initial", "reviewer:final"]);
    expect(kernel.inspect(actor, "reviewer").task.native_session).toEqual({ session_id: "ses_synthetic_reviewer" });
  } finally { await runtime.stop(); db.close(); rmSync(root, { recursive: true, force: true }); }
});
