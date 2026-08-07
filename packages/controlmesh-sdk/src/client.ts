import type {
  Artifact,
  ControlMeshError as ControlMeshErrorEnvelope,
  ProviderCapability,
  Task,
  TaskEvent,
  Topology,
} from "@controlmesh/protocol";
import {
  assertProtocolSchema,
  ProtocolValidationError,
  type ControlMeshSchemaName,
} from "@controlmesh/protocol";
import { ControlMeshRequestError, requestJson, streamSse } from "@controlmesh/runtime-facade";
import { ControlMeshError } from "./errors";

export interface ControlMeshClientOptions {
  baseUrl?: string;
  token?: string;
  fetch?: typeof fetch;
}

export interface ListTasksQuery {
  limit?: number;
}

export interface TaskList {
  items: Task[];
  total?: number;
  limit?: number;
}

export interface ProviderCapabilityList {
  items: ProviderCapability[];
  total?: number;
}

export class ControlMeshClient {
  private readonly baseUrl: string;
  private readonly token?: string;
  private readonly fetchImpl: typeof fetch;

  constructor(options: ControlMeshClientOptions = {}) {
    this.baseUrl = options.baseUrl ?? "http://127.0.0.1:8765";
    this.token = options.token;
    this.fetchImpl = options.fetch ?? fetch;
  }

  listTasks(query: ListTasksQuery = {}): Promise<TaskList> {
    const params = new URLSearchParams();
    if (query.limit !== undefined) {
      params.set("limit", String(query.limit));
    }
    return this.requestValidatedListEnvelope(
      `/api/v1/tasks${params.size ? `?${params}` : ""}`,
      "task.schema.json",
    );
  }

  getTask(taskId: string): Promise<Task> {
    return this.requestValidated(
      `/api/v1/tasks/${encodeURIComponent(taskId)}`,
      "task.schema.json",
    );
  }

  getTaskEvents(taskId: string): Promise<TaskEvent[]> {
    return this.requestValidatedList(
      `/api/v1/tasks/${encodeURIComponent(taskId)}/events`,
      "task-event.schema.json",
    );
  }

  async *subscribeTaskEvents(taskId: string): AsyncIterable<TaskEvent> {
    const events = streamSse<unknown>(
      `${this.baseUrl}/api/v1/tasks/${encodeURIComponent(taskId)}/events/stream`,
      { token: this.token, fetch: this.fetchImpl },
    );
    for await (const event of events) {
      assertProtocolSchema<TaskEvent>("task-event.schema.json", event);
      yield event;
    }
  }

  listArtifacts(taskId: string): Promise<Artifact[]> {
    return this.requestValidatedList(
      `/api/v1/tasks/${encodeURIComponent(taskId)}/artifacts`,
      "artifact.schema.json",
    );
  }

  downloadArtifact(taskId: string, relativePath: string): Promise<ArrayBuffer> {
    const params = new URLSearchParams({ relative_path: relativePath });
    return this.requestRaw(
      `/api/v1/tasks/${encodeURIComponent(taskId)}/artifacts/content?${params}`,
    );
  }

  async getProviderStatus(provider?: string): Promise<ProviderCapability[]> {
    const body = await this.requestValidatedListEnvelope<ProviderCapability>(
      "/api/v1/providers",
      "provider-capability.schema.json",
    );
    if (provider === undefined) {
      return body.items;
    }
    return body.items.filter((item) => item.name === provider);
  }

  async listTopologies(): Promise<Topology[]> {
    const body = await this.requestValidatedListEnvelope<Topology>(
      "/api/v1/topologies",
      "topology.schema.json",
    );
    return body.items;
  }

  private async requestValidated<T>(
    path: string,
    schemaName: ControlMeshSchemaName,
    options: { method?: string; body?: unknown } = {},
  ): Promise<T> {
    const value = await this.request<unknown>(path, options);
    assertProtocolSchema<T>(schemaName, value);
    return value;
  }

  private async requestValidatedList<T>(
    path: string,
    schemaName: ControlMeshSchemaName,
    options: { method?: string; body?: unknown } = {},
  ): Promise<T[]> {
    const value = await this.request<unknown>(path, options);
    if (!Array.isArray(value)) {
      throw new ProtocolValidationError(schemaName);
    }
    for (const item of value) {
      assertProtocolSchema<T>(schemaName, item);
    }
    return value;
  }

  private async requestValidatedListEnvelope<T>(
    path: string,
    schemaName: ControlMeshSchemaName,
  ): Promise<{ items: T[]; total?: number; limit?: number }> {
    const value = await this.request<unknown>(path);
    if (
      typeof value !== "object" ||
      value === null ||
      !("items" in value) ||
      !Array.isArray(value.items) ||
      ("total" in value && typeof value.total !== "number") ||
      ("limit" in value && typeof value.limit !== "number")
    ) {
      throw new ProtocolValidationError(schemaName);
    }
    for (const item of value.items) {
      assertProtocolSchema<T>(schemaName, item);
    }
    return value as { items: T[]; total?: number; limit?: number };
  }

  private request<T>(path: string, options: { method?: string; body?: unknown } = {}): Promise<T> {
    return this.wrapErrors(
      requestJson<T>(`${this.baseUrl}${path}`, {
        method: options.method,
        body: options.body,
        token: this.token,
        fetch: this.fetchImpl,
      }),
    );
  }

  private requestRaw(path: string): Promise<ArrayBuffer> {
    return this.wrapErrors(
      requestJson<ArrayBuffer>(`${this.baseUrl}${path}`, {
        token: this.token,
        fetch: this.fetchImpl,
        raw: true,
      }),
    );
  }

  private async wrapErrors<T>(promise: Promise<T>): Promise<T> {
    try {
      return await promise;
    } catch (error) {
      if (error instanceof ControlMeshRequestError) {
        assertProtocolSchema<ControlMeshErrorEnvelope>("error.schema.json", error.envelope);
        throw new ControlMeshError(error.envelope, { status: error.status });
      }
      throw error;
    }
  }
}
