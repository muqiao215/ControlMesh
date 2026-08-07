export interface RequestJsonOptions {
  method?: string;
  body?: unknown;
  token?: string;
  fetch?: typeof fetch;
  raw?: boolean;
}

export class ControlMeshRequestError extends Error {
  readonly status: number;
  readonly envelope: unknown;

  constructor(status: number, envelope: unknown) {
    super(`ControlMesh request failed with status ${status}`);
    this.name = "ControlMeshRequestError";
    this.status = status;
    this.envelope = envelope;
  }
}

export async function requestJson<T>(url: string, options: RequestJsonOptions = {}): Promise<T> {
  const fetchImpl = options.fetch ?? fetch;
  const headers = new Headers();
  if (options.token) {
    headers.set("Authorization", `Bearer ${options.token}`);
  }
  if (options.body !== undefined) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetchImpl(url, {
    method: options.method ?? "GET",
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });

  if (!response.ok) {
    const envelope = await response.json().catch(() => ({
      schema_version: "controlmesh.error.v1",
      code: "CORE_UNREACHABLE",
      message: `ControlMesh request failed with status ${response.status}`,
    }));
    throw new ControlMeshRequestError(response.status, envelope);
  }

  if (options.raw) {
    return (await response.arrayBuffer()) as T;
  }
  return (await response.json()) as T;
}
