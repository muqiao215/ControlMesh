import type { ControlMeshError as ControlMeshErrorEnvelope } from "@controlmesh/protocol";

export class ControlMeshError extends Error {
  readonly code: string;
  readonly status?: number;
  readonly details?: Record<string, unknown>;
  readonly retryable: boolean;
  readonly correlationId: string;

  constructor(envelope: ControlMeshErrorEnvelope, options: { status?: number } = {}) {
    super(envelope.message);
    this.name = "ControlMeshError";
    this.code = envelope.code;
    this.status = options.status;
    this.details = envelope.details;
    this.retryable = Boolean(envelope.retryable);
    this.correlationId =
      typeof envelope.correlation_id === "string" ? envelope.correlation_id : "";
  }
}
