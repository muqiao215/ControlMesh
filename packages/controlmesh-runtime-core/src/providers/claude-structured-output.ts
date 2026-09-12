import { assertProtocolSchema, controlmeshSchemas } from "@controlmesh/protocol";
import { canonical, digest, object, requireThat } from "../value";
import type { NativeMailboxBatch } from "./native-mailbox-input";

const names = ["team-structured-result.schema.json", "team-director-decision.schema.json", "team-judge-decision.schema.json"] as const;
export interface ClaudeStructuredOutput {
  schema_name: typeof names[number];
  bindings: { topology: string; substage?: string; worker_role?: string; round_index?: number };
  dispatch_round_index?: number;
}
export function decodeClaudeStructuredOutput(value: unknown): ClaudeStructuredOutput {
  requireThat(object(value) && names.includes(value.schema_name as typeof names[number]) && object(value.bindings), "invalid_claude_structured_contract");
  const worker = value.schema_name === names[0], director = value.schema_name === names[1], b = value.bindings;
  requireThat(canonical(Object.keys(value).sort()) === canonical(["schema_name", "bindings", ...(director ? ["dispatch_round_index"] : [])].sort())
    && canonical(Object.keys(b).sort()) === canonical((worker ? ["topology", "substage", "worker_role"] : ["topology", "round_index"]).sort()), "invalid_claude_structured_contract");
  requireThat(worker ? ["pipeline", "fanout_merge", "director_worker", "debate_judge"].includes(String(b.topology))
    && [b.substage, b.worker_role].every(text => typeof text === "string" && text.trim().length > 0 && text.length <= 128 && !text.includes("\0"))
    : b.topology === (director ? "director_worker" : "debate_judge") && Number.isSafeInteger(b.round_index) && Number(b.round_index) >= 1,
  "invalid_claude_structured_contract");
  if (director) requireThat(Number.isSafeInteger(value.dispatch_round_index)
    && [b.round_index, Number(b.round_index) + 1].includes(value.dispatch_round_index as number), "invalid_claude_structured_round");
  return structuredClone(value) as unknown as ClaudeStructuredOutput;
}

/** Only the attributed coordinator assignment can select a schema; ordinary Agent/history messages cannot. */
export function claudeTopologyOutput(batch?: NativeMailboxBatch): ClaudeStructuredOutput | undefined {
  if (!batch) return undefined;
  const messages = batch.messages.filter(message => message.origin === "schedule" && message.sender_task === null
    && message.kind === "handoff" && message.payload.schema_version === "controlmesh.topology_task_context.v1"
    && message.payload.source === "coordinator_topology");
  requireThat(messages.length <= 1, "claude_structured_assignment_ambiguous");
  const message = messages[0]; if (!message) return undefined;
  const p = message.payload, c = p.output_contract;
  requireThat(p.task_id === batch.task_id && message.recipient_task === batch.task_id
    && /^topology-input-[a-f0-9]{64}$/.test(message.message_id) && message.correlation_id === `topology:${p.run_id}`
    && object(c) && names.includes(c.schema_name as typeof names[number]) && object(c.required_values)
    && digest(c.schema) === digest(controlmeshSchemas[c.schema_name as typeof names[number]]), "claude_structured_assignment_changed");
  const director = p.topology === "director_worker" && ["planning", "director_deciding", "repairing"].includes(String(p.substage));
  const judge = p.topology === "debate_judge" && p.substage === "judging";
  const substage = (["fanout_merge", "director_worker"].includes(String(p.topology)) && p.substage === "dispatching")
    || (p.topology === "debate_judge" && p.substage === "candidate_round") ? "collecting" : p.substage;
  const bindings = { topology: p.topology, ...(director || judge ? { round_index: p.round_index } : { substage, worker_role: p.worker_role }) };
  requireThat(c.schema_name === names[director ? 1 : judge ? 2 : 0] && digest(c.required_values) === digest(bindings)
    && (!director || c.dispatch_round_index === Number(p.round_index) + (p.substage === "planning" ? 0 : 1)), "claude_structured_assignment_changed");
  return decodeClaudeStructuredOutput({ schema_name: c.schema_name, bindings,
    ...(director ? { dispatch_round_index: c.dispatch_round_index } : {}) });
}

/** Build only a bundled, self-contained schema; never resolve model-supplied schema URLs. */
export function claudeStructuredSchema(input: ClaudeStructuredOutput): Record<string, unknown> {
  const contract = decodeClaudeStructuredOutput(input), schema = structuredClone(controlmeshSchemas[contract.schema_name]) as Record<string, any>;
  requireThat(!canonical(schema).includes('"$ref"'), "claude_structured_schema_reference_unsupported");
  // The pinned CLI uses Draft 7. These schemas use its shared vocabulary; CM still validates the original Draft 2020-12 contract.
  const common = new Set(["$id", "$schema", "title", "description", "type", "properties", "additionalProperties", "required", "const", "enum",
    "allOf", "anyOf", "if", "then", "else", "items", "minimum", "maximum", "minLength", "minItems", "maxItems"]);
  const check = (value: unknown): void => {
    if (typeof value === "boolean") return;
    requireThat(object(value), "claude_structured_schema_dialect_unsupported");
    for (const [key, child] of Object.entries(value)) {
      requireThat(common.has(key), "claude_structured_schema_dialect_unsupported");
      if (key === "properties") { requireThat(object(child), "claude_structured_schema_dialect_unsupported"); Object.values(child).forEach(check); }
      else if (["allOf", "anyOf"].includes(key)) { requireThat(Array.isArray(child), "claude_structured_schema_dialect_unsupported"); child.forEach(check); }
      else if (["if", "then", "else", "items", "additionalProperties"].includes(key)) check(child);
    }
  };
  check(schema); schema.$schema = "http://json-schema.org/draft-07/schema#"; delete schema.$id;
  // const implies this type in JSON Schema, but native model tool adapters benefit from an explicit declaration.
  requireThat(schema.properties.schema_version.const === 1, "claude_structured_schema_version_unsupported");
  schema.properties.schema_version = { ...schema.properties.schema_version, type: "integer" };
  for (const [key, value] of Object.entries(contract.bindings)) schema.properties[key] = { ...schema.properties[key], const: value };
  if (contract.dispatch_round_index !== undefined) {
    delete schema.properties.round_index.const;
    schema.allOf = [...(schema.allOf ?? []), { if: { properties: { decision: { const: "dispatch_workers" } } },
      then: { properties: { round_index: { const: contract.dispatch_round_index } } },
      else: { properties: { round_index: { const: contract.bindings.round_index } } } }];
  }
  return schema;
}
export function verifyClaudeStructuredValue(contract: ClaudeStructuredOutput, value: unknown): Record<string, unknown> {
  contract = decodeClaudeStructuredOutput(contract);
  assertProtocolSchema(contract.schema_name, value); requireThat(object(value), "claude_structured_result_missing");
  for (const [key, expected] of Object.entries(contract.bindings)) requireThat(value[key] === (key === "round_index" && value.decision === "dispatch_workers"
    && contract.dispatch_round_index !== undefined ? contract.dispatch_round_index : expected), "claude_structured_result_assignment_changed");
  return value;
}
/** Native source proof is checked after stream proof; schema validity alone cannot mint a successful tool receipt. */
export function verifyClaudeStructuredTools(contract: ClaudeStructuredOutput, value: unknown,
  tools: readonly { name: string; input: Record<string, unknown>; output: string; is_error: boolean }[]): void {
  verifyClaudeStructuredValue(contract, value);
  const calls = tools.filter(tool => tool.name === "StructuredOutput");
  requireThat(calls.length === 1 && !calls[0]!.is_error && calls[0]!.output === "Structured output provided successfully"
    && digest(calls[0]!.input) === digest(value), "claude_structured_native_receipt_unproven");
}
