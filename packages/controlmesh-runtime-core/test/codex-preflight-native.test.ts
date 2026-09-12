import { codexTextResponse } from "./helpers/codex-responses";
import { expect, test } from "bun:test";
import { CodexPreflight } from "../src/providers/codex-preflight";

// Opt-in protocol qualification of an installed binary. All credentials and model responses are synthetic.
const executable = process.env.CM_CODEX_TEST_EXECUTABLE;
test.skipIf(!executable)("installed Codex uses the selected local endpoint and classifies native quota without a model service", async () => {
  const requests: { path: string; model: unknown; tools: string[] }[] = [];
  let quota = false;
  const server = Bun.serve({ hostname: "127.0.0.1", port: 0, async fetch(request) {
    const value = await request.json() as Record<string, any>;
    requests.push({ path: new URL(request.url).pathname, model: value.model, tools: (value.tools ?? []).map((tool: any) => tool.name ?? tool.type) });
    if (quota) return Response.json({ error: { message: "insufficient_quota", code: "insufficient_quota", type: "insufficient_quota" } }, { status: 402 });
    return codexTextResponse(value.model, "PONG");
  } });
  const input = { executable: executable!, model: "gpt-5.5", native_configuration: {}, environment: { OPENAI_BASE_URL: `http://127.0.0.1:${server.port}/v1`, OPENAI_API_KEY: "local-fixture-only" },
    auth_json: JSON.stringify({ OPENAI_API_KEY: "local-fixture-only" }), timeout_ms: 15000, assertCurrent() {} };
  try {
    expect((await new CodexPreflight().probe(input)).observation.status).toBe("ready");
    expect(requests).toHaveLength(1); expect(requests[0]).toMatchObject({ path: "/v1/responses", model: input.model });
    expect(requests[0].tools).not.toContain("exec_command"); expect(requests[0].tools).not.toContain("shell");
    // Native built-ins still exist. No claim of a native zero-tool configuration or general sandbox qualification.
    quota = true;
    expect((await new CodexPreflight().probe(input)).observation.reason).toBe("quota_exhausted");
    expect(requests).toHaveLength(2);
  } finally { await server.stop(true); }
}, 35000);
