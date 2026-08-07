import { expect, test } from "bun:test";

import { ControlMeshClient, ControlMeshError, ProtocolValidationError } from "../src/index";

test("listTasks calls the v1 task facade and preserves protocol fields", async () => {
  const calls: string[] = [];
  const client = new ControlMeshClient({
    baseUrl: "http://controlmesh.test",
    token: "test-token",
    fetch: async (input, init) => {
      calls.push(String(input));
      expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer test-token");
      return Response.json({
        items: [
          {
            schema_version: "controlmesh.task.v1",
            task_id: "task-1",
            chat_id: 1,
            parent_agent: "main",
            status: "running",
            created_at: 1,
          },
        ],
        limit: 5,
        total: 1,
      });
    },
  });

  const result = await client.listTasks({ limit: 5 });

  expect(calls).toEqual(["http://controlmesh.test/api/v1/tasks?limit=5"]);
  expect(result.items[0].schema_version).toBe("controlmesh.task.v1");
  expect(result.items[0].task_id).toBe("task-1");
});

test("getProviderStatus unwraps provider capability list responses", async () => {
  const client = new ControlMeshClient({
    baseUrl: "http://controlmesh.test",
    fetch: async () =>
      Response.json({
        items: [
          {
            schema_version: "controlmesh.provider_capability.v1",
            name: "codex",
            available: true,
            health: "ok",
          },
          {
            schema_version: "controlmesh.provider_capability.v1",
            name: "gemini",
            available: false,
            health: "unavailable",
          },
        ],
        total: 2,
      }),
  });

  const providers = await client.getProviderStatus("codex");

  expect(providers).toHaveLength(1);
  expect(providers[0].name).toBe("codex");
  expect(providers[0].health).toBe("ok");
});

test("listTopologies validates Python-projected ownership graphs", async () => {
  const client = new ControlMeshClient({
    baseUrl: "http://controlmesh.test",
    fetch: async (input) => {
      expect(String(input)).toBe("http://controlmesh.test/api/v1/topologies");
      return Response.json({
        items: [
          {
            schema_version: "controlmesh.topology.v1",
            topology_id: "alpha-team",
            nodes: [{ id: "agent:main", kind: "agent", role: "leader" }],
            edges: [],
          },
        ],
        total: 1,
      });
    },
  });

  const topologies = await client.listTopologies();

  expect(topologies[0].topology_id).toBe("alpha-team");
});

test("getTaskEvents reads v1 task events", async () => {
  const client = new ControlMeshClient({
    baseUrl: "http://controlmesh.test",
    fetch: async (input) => {
      expect(String(input)).toBe("http://controlmesh.test/api/v1/tasks/task-1/events");
      return Response.json([
        {
          schema_version: "controlmesh.task_event.v1",
          event_id: "event-1",
          task_id: "task-1",
          event_type: "task.lifecycle.started",
          status: "running",
          created_at: "2026-04-11T10:05:00+00:00",
        },
      ]);
    },
  });

  const events = await client.getTaskEvents("task-1");

  expect(events).toHaveLength(1);
  expect(events[0].schema_version).toBe("controlmesh.task_event.v1");
});

test("listArtifacts reads Python-resolved artifact metadata", async () => {
  const client = new ControlMeshClient({
    baseUrl: "http://controlmesh.test",
    fetch: async (input) => {
      expect(String(input)).toBe("http://controlmesh.test/api/v1/tasks/task-1/artifacts");
      return Response.json([
        {
          schema_version: "controlmesh.artifact.v1",
          task_id: "task-1",
          relative_path: "generated/EVIDENCE.json",
          name: "EVIDENCE.json",
          mime: "application/json",
          size: 42,
        },
      ]);
    },
  });

  const artifacts = await client.listArtifacts("task-1");

  expect(artifacts).toHaveLength(1);
  expect(artifacts[0].schema_version).toBe("controlmesh.artifact.v1");
  expect(artifacts[0].relative_path).toBe("generated/EVIDENCE.json");
  expect(artifacts[0].relative_path.startsWith("/")).toBe(false);
});

test("downloadArtifact uses task id and metadata relative path", async () => {
  const client = new ControlMeshClient({
    baseUrl: "http://controlmesh.test",
    token: "test-token",
    fetch: async (input, init) => {
      expect(String(input)).toBe(
        "http://controlmesh.test/api/v1/tasks/task-1/artifacts/content?relative_path=reports%2Ffinal+result.txt",
      );
      expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer test-token");
      return new Response(new Uint8Array([1, 2, 3]));
    },
  });

  const content = await client.downloadArtifact("task-1", "reports/final result.txt");

  expect(Array.from(new Uint8Array(content))).toEqual([1, 2, 3]);
});

test("protocol error envelopes become ControlMeshError", async () => {
  const client = new ControlMeshClient({
    baseUrl: "http://controlmesh.test",
    fetch: async () =>
      Response.json(
        {
          schema_version: "controlmesh.error.v1",
          code: "TASK_NOT_FOUND",
          message: "task not found",
          retryable: false,
        },
        { status: 404 },
      ),
  });

  await expect(client.getTask("missing")).rejects.toBeInstanceOf(ControlMeshError);
  await expect(client.getTask("missing")).rejects.toMatchObject({
    code: "TASK_NOT_FOUND",
    status: 404,
    retryable: false,
  });
});

test("task list rejects malformed protocol items and envelopes", async () => {
  const malformedItem = new ControlMeshClient({
    fetch: async () => Response.json({ items: [{ schema_version: "controlmesh.task.v1" }] }),
  });
  const malformedEnvelope = new ControlMeshClient({
    fetch: async () => Response.json({ items: [], total: "one" }),
  });

  await expect(malformedItem.listTasks()).rejects.toBeInstanceOf(ProtocolValidationError);
  await expect(malformedEnvelope.listTasks()).rejects.toBeInstanceOf(ProtocolValidationError);
});

test("event, artifact, and provider reads reject malformed protocol items", async () => {
  const responses = [
    [{ schema_version: "controlmesh.task_event.v1", task_id: "task-1" }],
    [{ schema_version: "controlmesh.artifact.v1", task_id: "task-1" }],
    { items: [{ schema_version: "controlmesh.provider_capability.v1", name: "codex" }] },
  ];
  const client = new ControlMeshClient({
    fetch: async () => Response.json(responses.shift()),
  });

  await expect(client.getTaskEvents("task-1")).rejects.toBeInstanceOf(ProtocolValidationError);
  await expect(client.listArtifacts("task-1")).rejects.toBeInstanceOf(ProtocolValidationError);
  await expect(client.getProviderStatus()).rejects.toBeInstanceOf(ProtocolValidationError);
});

test("topology reads reject graphs without authoritative node identities", async () => {
  const client = new ControlMeshClient({
    fetch: async () =>
      Response.json({
        items: [
          {
            schema_version: "controlmesh.topology.v1",
            topology_id: "alpha-team",
            nodes: [{ role: "leader" }],
            edges: [],
          },
        ],
      }),
  });

  await expect(client.listTopologies()).rejects.toBeInstanceOf(ProtocolValidationError);
});

test("malformed error envelopes are rejected before SDK error mapping", async () => {
  const client = new ControlMeshClient({
    fetch: async () =>
      Response.json(
        { schema_version: "controlmesh.error.v1", message: "missing code" },
        { status: 500 },
      ),
  });

  await expect(client.getTask("task-1")).rejects.toBeInstanceOf(ProtocolValidationError);
});
