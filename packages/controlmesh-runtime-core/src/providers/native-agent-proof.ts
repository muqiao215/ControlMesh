import { assertProtocolSchema, type NativeAgentCallReceipt, type NativeAgentProof } from "@controlmesh/protocol";
import { canonical, digest, identifier, requireThat } from "../value";
import type { NativeAgentToolResult } from "./native-agent-journal";

/** Match bounded hashes on the coordinator without transferring native histories or tool text. */
export function nativeAgentProof(effectId: string, native: readonly NativeAgentToolResult[]): NativeAgentProof & Record<string, unknown> {
  identifier(effectId);
  const calls = new Map<string, NativeAgentCallReceipt>();
  for (const actual of native.filter(call => call.tool.startsWith("controlmesh_"))) {
    identifier(actual.input.request_id);
    requireThat(Buffer.byteLength(canonical(actual.input)) <= 16384 && Buffer.byteLength(actual.output) <= 16384, "native_agent_call_too_large");
    const receipt = { call_id: digest([effectId, actual.input.request_id]), tool: actual.tool,
      input_digest: digest(actual.input), output_digest: digest(actual.output) };
    assertProtocolSchema<NativeAgentCallReceipt>("native-agent-call-receipt.schema.json", receipt);
    const previous = calls.get(receipt.call_id);
    requireThat(!previous || digest(previous) === digest(receipt), "native_agent_duplicate_changed");
    calls.set(receipt.call_id, receipt);
    requireThat(calls.size <= 32, "native_agent_call_budget_exhausted");
  }
  return { call_receipts: [...calls.values()].sort((a, b) => a.call_id.localeCompare(b.call_id)) };
}
