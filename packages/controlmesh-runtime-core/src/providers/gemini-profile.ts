import { isAbsolute } from "node:path";
import { requireThat } from "../value";

/** Native policy material only. Loading/effective-rule verification remains process admission. */
export function geminiToolPolicy(allowedTools: readonly string[]): string {
  requireThat(Array.isArray(allowedTools) && allowedTools.length <= 256
    && allowedTools.every(name => typeof name === "string" && /^[A-Za-z][A-Za-z0-9_]{0,127}$/.test(name)), "invalid_gemini_tool_allowlist");
  const names = [...new Set(allowedTools)].sort();
  const rows = ['[[rule]]\ntoolName = "*"\ndecision = "deny"\npriority = 998\n'];
  for (const name of names) rows.push(`[[rule]]\ntoolName = "${name}"\ndecision = "allow"\npriority = 999\n`);
  return rows.join("\n");
}

export interface GeminiResumeProfile {
  executable: string;
  session_id: string;
  model: string;
  policy_path: string;
  prompt: string;
}

/** No arbitrary CLI extras: session, model, output and policy have a single owner. */
export function geminiResumeCommand(input: GeminiResumeProfile) {
  requireThat(typeof input.executable === "string" && isAbsolute(input.executable) && !/[\x00\r\n]/.test(input.executable), "invalid_provider_executable");
  requireThat(typeof input.session_id === "string" && /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(input.session_id), "invalid_native_session_id");
  requireThat(typeof input.model === "string" && /^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$/.test(input.model), "invalid_gemini_model");
  requireThat(typeof input.policy_path === "string" && isAbsolute(input.policy_path) && !/[\x00\r\n]/.test(input.policy_path), "invalid_gemini_policy_path");
  requireThat(typeof input.prompt === "string" && input.prompt.trim().length > 0 && Buffer.byteLength(input.prompt) <= 1024 * 1024 && !input.prompt.includes("\0"), "invalid_gemini_prompt");
  return { command: [input.executable, "--resume", input.session_id, "--model", input.model,
    "--output-format", "stream-json", "--approval-mode", "default", "--ignore-env", "--admin-policy", input.policy_path, "-p", ""], stdin_text: input.prompt };
}
