import type { PreflightObservation } from "./opencode-events";

/** Provider-neutral evidence retained by the shared readiness budget. */
export interface ProviderProbeReport {
  model: string;
  config_digest: string;
  observation: PreflightObservation;
  cli_version: string;
  permission_digest: string | null;
  /** Native advertised count when inspected; null when the CLI does not attest it. */
  tool_count: number | null;
  model_invoked: boolean;
  duration_ms: number;
  runtime_digest?: string;
  /** Process facts only; no raw stderr, credentials or private paths. */
  process_reason?: string;
  process_exit_code?: number | null;
}
