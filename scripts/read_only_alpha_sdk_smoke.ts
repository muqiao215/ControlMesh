import { ControlMeshClient } from "../packages/controlmesh-sdk/src/index";

const [baseUrl, token, expectedTaskId, expectedArtifactPath, forbiddenPath] = Bun.argv.slice(2);

if (!baseUrl || !token || !expectedTaskId || !expectedArtifactPath || !forbiddenPath) {
  throw new Error("expected base URL, token, task ID, artifact path, and forbidden path");
}

const client = new ControlMeshClient({ baseUrl, token });
const tasks = await client.listTasks({ limit: 10 });
if (tasks.items.length !== 1 || tasks.items[0]?.task_id !== expectedTaskId) {
  throw new Error(`unexpected tasks: ${JSON.stringify(tasks)}`);
}

const task = await client.getTask(expectedTaskId);
const events = await client.getTaskEvents(expectedTaskId);
const artifacts = await client.listArtifacts(expectedTaskId);
const providers = await client.getProviderStatus();
const topologies = await client.listTopologies();
const artifact = artifacts.find((item) => item.relative_path === expectedArtifactPath);

if (!artifact || artifacts.some((item) => item.relative_path === "private-link.txt")) {
  throw new Error(`artifact containment failed: ${JSON.stringify(artifacts)}`);
}
if (events.length !== 1 || providers.length !== 1 || topologies.length !== 0) {
  throw new Error("unexpected event/provider/topology projection");
}

const content = new TextDecoder().decode(
  await client.downloadArtifact(expectedTaskId, expectedArtifactPath),
);
if (content !== "read-only alpha artifact\n") {
  throw new Error(`unexpected artifact content: ${JSON.stringify(content)}`);
}

const mutationResponse = await fetch(`${baseUrl}/api/v1/tasks`, {
  method: "POST",
  headers: {
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json",
  },
  body: JSON.stringify({ prompt: "must not run" }),
});
if (mutationResponse.status !== 405) {
  throw new Error(`mutation route unexpectedly available: ${mutationResponse.status}`);
}

const legacyUploadResponse = await fetch(`${baseUrl}/upload`, { method: "POST" });
if (legacyUploadResponse.status !== 404) {
  throw new Error(`legacy mutation surface leaked: ${legacyUploadResponse.status}`);
}

const prototype = ControlMeshClient.prototype as unknown as Record<string, unknown>;
for (const unsupported of [
  "createTask",
  "tellTask",
  "resumeTask",
  "cancelTask",
  "sendAskParentResponse",
  "runDoctor",
]) {
  if (unsupported in prototype) {
    throw new Error(`unsupported SDK mutation leaked: ${unsupported}`);
  }
}

const projection = JSON.stringify({ task, events, artifacts, providers, topologies });
if (projection.includes(forbiddenPath) || projection.includes("private.txt")) {
  throw new Error("private runtime path leaked through the facade");
}

console.log(
  JSON.stringify({
    status: "ok",
    task_id: task.task_id,
    events: events.length,
    artifacts: artifacts.length,
    providers: providers.length,
    mutation_status: mutationResponse.status,
    legacy_upload_status: legacyUploadResponse.status,
  }),
);
