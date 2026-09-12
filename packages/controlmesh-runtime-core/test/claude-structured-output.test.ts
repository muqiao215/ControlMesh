import { expect, test } from "bun:test";
import { controlmeshSchemas } from "@controlmesh/protocol";
import { claudeStructuredSchema, claudeTopologyOutput, decodeClaudeStructuredOutput, verifyClaudeStructuredTools, verifyClaudeStructuredValue } from "../src/providers/claude-structured-output";
import type { NativeMailboxBatch } from "../src/providers/native-mailbox-input";
import { decodeTeamResult } from "../src/team-result-validation";
import { decodeDirectorDecision, decodeJudgeDecision } from "../src/team-control-decision";
import { digest } from "../src/value";
const worker = { schema_name: "team-structured-result.schema.json" as const, bindings: { topology: "pipeline", substage: "worker_running", worker_role: "worker" } };
const value = () => ({ ...decodeTeamResult({ ...worker.bindings, status: "completed", summary: "Current result" }) });
function batch(): NativeMailboxBatch {
  return { schema_version: "controlmesh.native_mailbox.v1", task_id: "worker", messages: [{
    schema_version: "controlmesh.agent_mailbox_message.v1",
    message_id: `topology-input-${"a".repeat(64)}`, recipient_task: "worker", sender_task: null, sender_principal: "operator", sequence: 1,
    correlation_id: "topology:run", causation_id: null, origin: "schedule", kind: "handoff", remaining_hops: 0,
    created_at: 1, expires_at: 1000, status: "received", payload: { schema_version: "controlmesh.topology_task_context.v1", source: "coordinator_topology",
      task_id: "worker", parent_task_id: "root", run_id: "run", topology: "pipeline", substage: "worker_running", worker_role: "worker",
      output_contract: { schema_name: worker.schema_name, schema: controlmeshSchemas[worker.schema_name], required_values: worker.bindings } },
  }] };
}
test("only an attributed coordinator assignment selects the bundled structured schema", () => {
  expect(claudeTopologyOutput()).toBeUndefined(); expect(claudeTopologyOutput(batch())).toEqual(worker);
  for (const change of ["origin", "sender"] as const) {
    const input = batch(); if (change === "origin") input.messages[0]!.origin = "human_request"; else input.messages[0]!.sender_task = "agent";
    expect(claudeTopologyOutput(input)).toBeUndefined();
  }
  const schema = claudeStructuredSchema(worker);
  expect(schema.$schema).toBe("http://json-schema.org/draft-07/schema#"); expect(schema.$id).toBeUndefined();
  expect(controlmeshSchemas[worker.schema_name].$schema).toBe("https://json-schema.org/draft/2020-12/schema");
  expect(schema).toMatchObject({ properties: { topology: { const: "pipeline" }, worker_role: { const: "worker" } }, additionalProperties: false });
  expect(digest(controlmeshSchemas[worker.schema_name])).toBe(digest((batch().messages[0]!.payload.output_contract as { schema: unknown }).schema));
});
for (const field of ["task", "schema", "binding", "correlation", "duplicate"] as const) test(`structured assignment refuses changed ${field}`, () => {
  const input = batch(), p = input.messages[0]!.payload;
  if (field === "task") p.task_id = "foreign";
  if (field === "schema") p.output_contract = { ...(p.output_contract as object), schema: { type: "object" } };
  if (field === "binding") p.worker_role = "foreign";
  if (field === "correlation") input.messages[0]!.correlation_id = "foreign";
  if (field === "duplicate") input.messages.push(structuredClone(input.messages[0]!));
  expect(() => claudeTopologyOutput(input)).toThrow();
});
test("native structured result must match the full schema and exactly one successful source tool", () => {
  const output = value(), tool = { name: "StructuredOutput", input: output, output: "Structured output provided successfully", is_error: false };
  expect(verifyClaudeStructuredValue(worker, output)).toEqual(output);
  verifyClaudeStructuredTools(worker, output, [tool]);
  for (const tools of [[], [tool, tool], [{ ...tool, is_error: true }], [{ ...tool, output: "claimed success" }], [{ ...tool, input: { ...output, summary: "changed" } }]])
    expect(() => verifyClaudeStructuredTools(worker, output, tools)).toThrow("claude_structured_native_receipt_unproven");
  expect(() => verifyClaudeStructuredValue(worker, { ...output, worker_role: "foreign" })).toThrow("claude_structured_result_assignment_changed");
  expect(() => verifyClaudeStructuredValue(worker, { ...output, injected: "unexpected" })).toThrow();
  expect(() => decodeClaudeStructuredOutput({ ...worker, schema: {} })).toThrow();
});
test("generation explicitly types the schema version without coercing model strings in acceptance", () => {
  const contracts = [worker,
    { schema_name: "team-director-decision.schema.json" as const, bindings: { topology: "director_worker", round_index: 1 }, dispatch_round_index: 1 },
    { schema_name: "team-judge-decision.schema.json" as const, bindings: { topology: "debate_judge", round_index: 1 } }];
  for (const contract of contracts) expect(claudeStructuredSchema(contract)).toMatchObject({ properties: { schema_version: { type: "integer", const: 1 } } });
  expect(() => verifyClaudeStructuredValue(worker, { ...value(), schema_version: "1" })).toThrow();
});
test("controller schema binds the correct decision-dependent round without replacing frozen budgets", () => {
  const director = { schema_name: "team-director-decision.schema.json" as const, bindings: { topology: "director_worker", round_index: 2 }, dispatch_round_index: 3 };
  const dispatch = { ...decodeDirectorDecision({ topology: "director_worker", round_index: 3, decision: "dispatch_workers", dispatch_roles: ["worker"], summary: "Continue" }) };
  expect(verifyClaudeStructuredValue(director, dispatch)).toEqual(dispatch);
  expect(() => verifyClaudeStructuredValue(director, { ...dispatch, round_index: 2 })).toThrow("claude_structured_result_assignment_changed");
  const done = { ...decodeDirectorDecision({ topology: "director_worker", round_index: 2, decision: "complete", summary: "Complete" }) };
  expect(verifyClaudeStructuredValue(director, done)).toEqual(done);
  expect(claudeStructuredSchema(director)).toMatchObject({ allOf: expect.arrayContaining([{ if: { properties: { decision: { const: "dispatch_workers" } } },
    then: { properties: { round_index: { const: 3 } } }, else: { properties: { round_index: { const: 2 } } } }]) });
  const judge = { schema_name: "team-judge-decision.schema.json" as const, bindings: { topology: "debate_judge", round_index: 2 } };
  const selected = { ...decodeJudgeDecision({ topology: "debate_judge", round_index: 2, decision: "select_winner", winner_role: "worker", summary: "Selected" }) };
  expect(verifyClaudeStructuredValue(judge, selected)).toEqual(selected);
});
