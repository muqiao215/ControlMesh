import type { PreflightObservation } from "./opencode-events";

/** Provider-neutral evidence retained by the shared readiness budget. */
export interface ProviderProbeReport {
  model: string;
  config_digest: string;
  observation: PreflightObservation;
  cli_version: string;
  permission_digest: string | null;
  tool_count: number;
  model_invoked: boolean;
  duration_ms: number;
  runtime_digest?: string;
}
