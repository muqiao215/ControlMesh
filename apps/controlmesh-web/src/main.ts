import { ControlMeshClient } from "@controlmesh/sdk";
import type { Artifact, ProviderCapability, Task, TaskEvent, Topology } from "@controlmesh/sdk";

type ViewState = {
  baseUrl: string;
  token: string;
  tasks: Task[];
  selectedTaskId: string;
  events: TaskEvent[];
  artifacts: Artifact[];
  providers: ProviderCapability[];
  topologies: Topology[];
  status: string;
};

const app = document.querySelector<HTMLElement>("#app");
const state: ViewState = {
  baseUrl: localStorage.getItem("controlmesh.baseUrl") || "http://127.0.0.1:8765",
  token: localStorage.getItem("controlmesh.token") || "",
  tasks: [],
  selectedTaskId: "",
  events: [],
  artifacts: [],
  providers: [],
  topologies: [],
  status: "Idle",
};

function client(): ControlMeshClient {
  return new ControlMeshClient({
    baseUrl: state.baseUrl,
    token: state.token || undefined,
  });
}

function selectedTask(): Task | undefined {
  return state.tasks.find((task) => task.task_id === state.selectedTaskId);
}

function render(): void {
  if (!app) {
    return;
  }
  const task = selectedTask();
  app.innerHTML = `
    <main class="shell">
      <header class="topbar">
        <div>
          <h1>ControlMesh</h1>
          <span class="status">${escapeHtml(state.status)}</span>
        </div>
        <form id="connection-form" class="connection">
          <label>
            <span>API</span>
            <input name="baseUrl" value="${escapeAttribute(state.baseUrl)}" />
          </label>
          <label>
            <span>Token</span>
            <input name="token" type="password" value="${escapeAttribute(state.token)}" />
          </label>
          <button type="submit">Refresh</button>
        </form>
      </header>

      <section class="layout">
        <aside class="task-list">
          <div class="section-title">
            <h2>Tasks</h2>
            <span>${state.tasks.length}</span>
          </div>
          <div class="rows">
            ${state.tasks.map(renderTaskRow).join("") || `<div class="empty">No tasks</div>`}
          </div>
        </aside>

        <section class="detail">
          ${
            task
              ? `
                <div class="detail-head">
                  <div>
                    <h2>${escapeHtml(task.name || task.task_id)}</h2>
                    <span>${escapeHtml(task.task_id)}</span>
                  </div>
                  <strong class="state state-${escapeClass(task.status)}">${escapeHtml(task.status)}</strong>
                </div>
                <dl class="meta">
                  <div><dt>Provider</dt><dd>${escapeHtml(task.provider || "-")}</dd></div>
                  <div><dt>Model</dt><dd>${escapeHtml(task.model || "-")}</dd></div>
                  <div><dt>Session</dt><dd>${escapeHtml(task.session_id || "-")}</dd></div>
                  <div><dt>Created</dt><dd>${escapeHtml(String(task.created_at || "-"))}</dd></div>
                </dl>
                <p class="preview">${escapeHtml(task.prompt_preview || "")}</p>
                <div class="columns">
                  ${renderEvents()}
                  ${renderArtifacts()}
                </div>
              `
              : `<div class="empty detail-empty">Select a task</div>`
          }
        </section>

        <aside class="providers">
          <div class="section-title">
            <h2>Providers</h2>
            <span>${state.providers.length}</span>
          </div>
          <div class="rows">
            ${state.providers.map(renderProvider).join("") || `<div class="empty">No providers</div>`}
          </div>
          <div class="section-title topology-title">
            <h2>Topologies</h2>
            <span>${state.topologies.length}</span>
          </div>
          <div class="rows">
            ${state.topologies.map(renderTopology).join("") || `<div class="empty">No topologies</div>`}
          </div>
        </aside>
      </section>
    </main>
  `;
  wireEvents();
}

function renderTaskRow(task: Task): string {
  const active = task.task_id === state.selectedTaskId ? " active" : "";
  return `
    <button class="task-row${active}" data-task-id="${escapeAttribute(task.task_id)}">
      <span>${escapeHtml(task.name || task.task_id)}</span>
      <small>${escapeHtml(task.provider || "unknown")}</small>
      <strong class="state state-${escapeClass(task.status)}">${escapeHtml(task.status)}</strong>
    </button>
  `;
}

function renderEvents(): string {
  return `
    <section class="panel">
      <div class="section-title">
        <h3>Events</h3>
        <span>${state.events.length}</span>
      </div>
      <div class="rows compact">
        ${
          state.events
            .map(
              (event) => `
                <article class="event">
                  <strong>${escapeHtml(event.event_type)}</strong>
                  <small>${escapeHtml(event.status || "")}</small>
                  <time>${escapeHtml(event.created_at)}</time>
                </article>
              `,
            )
            .join("") || `<div class="empty">No events</div>`
        }
      </div>
    </section>
  `;
}

function renderArtifacts(): string {
  return `
    <section class="panel">
      <div class="section-title">
        <h3>Artifacts</h3>
        <span>${state.artifacts.length}</span>
      </div>
      <div class="rows compact">
        ${
          state.artifacts
            .map(
              (artifact) => `
                <article class="artifact">
                  <div>
                    <strong>${escapeHtml(artifact.relative_path)}</strong>
                    <small>${escapeHtml(artifact.mime || "")}</small>
                    <span>${formatBytes(artifact.size)}</span>
                  </div>
                  <button
                    type="button"
                    class="artifact-download"
                    data-artifact-path="${escapeAttribute(artifact.relative_path)}"
                    data-artifact-name="${escapeAttribute(artifact.name || artifact.relative_path)}"
                    data-artifact-mime="${escapeAttribute(artifact.mime || "application/octet-stream")}"
                  >Download</button>
                </article>
              `,
            )
            .join("") || `<div class="empty">No artifacts</div>`
        }
      </div>
    </section>
  `;
}

function renderProvider(provider: ProviderCapability): string {
  return `
    <article class="provider">
      <strong>${escapeHtml(provider.name)}</strong>
      <span class="health health-${escapeClass(provider.health)}">${escapeHtml(provider.health)}</span>
      <small>${provider.available ? "available" : "unavailable"}</small>
    </article>
  `;
}

function renderTopology(topology: Topology): string {
  return `
    <article class="topology">
      <strong>${escapeHtml(topology.name || topology.topology_id)}</strong>
      <small>${topology.nodes.length} nodes</small>
      <span>${topology.edges.length} edges</span>
    </article>
  `;
}

function wireEvents(): void {
  document.querySelector("#connection-form")?.addEventListener("submit", (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget as HTMLFormElement);
    state.baseUrl = String(form.get("baseUrl") || "").trim();
    state.token = String(form.get("token") || "");
    localStorage.setItem("controlmesh.baseUrl", state.baseUrl);
    localStorage.setItem("controlmesh.token", state.token);
    void load();
  });

  document.querySelectorAll<HTMLButtonElement>("[data-task-id]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedTaskId = button.dataset.taskId || "";
      void loadTaskDetail();
    });
  });

  document.querySelectorAll<HTMLButtonElement>("[data-artifact-path]").forEach((button) => {
    button.addEventListener("click", () => {
      void downloadArtifact(button);
    });
  });
}

async function downloadArtifact(button: HTMLButtonElement): Promise<void> {
  const relativePath = button.dataset.artifactPath || "";
  if (!state.selectedTaskId || !relativePath) {
    return;
  }
  button.disabled = true;
  try {
    const content = await client().downloadArtifact(state.selectedTaskId, relativePath);
    const blob = new Blob([content], {
      type: button.dataset.artifactMime || "application/octet-stream",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = button.dataset.artifactName || "artifact";
    link.click();
    URL.revokeObjectURL(url);
    state.status = "Downloaded";
  } catch (error) {
    state.status = error instanceof Error ? error.message : "Unable to download artifact";
  } finally {
    button.disabled = false;
    render();
  }
}

async function load(): Promise<void> {
  state.status = "Loading";
  render();
  try {
    const cm = client();
    const [tasks, providers, topologies] = await Promise.all([
      cm.listTasks({ limit: 50 }),
      cm.getProviderStatus(),
      cm.listTopologies(),
    ]);
    state.tasks = tasks.items;
    state.providers = providers;
    state.topologies = topologies;
    state.selectedTaskId = state.selectedTaskId || state.tasks[0]?.task_id || "";
    await loadTaskDetail(false);
    state.status = "Connected";
  } catch (error) {
    state.status = error instanceof Error ? error.message : "Unable to connect";
    state.events = [];
    state.artifacts = [];
  }
  render();
}

async function loadTaskDetail(shouldRender = true): Promise<void> {
  if (!state.selectedTaskId) {
    state.events = [];
    state.artifacts = [];
    if (shouldRender) {
      render();
    }
    return;
  }
  try {
    const cm = client();
    const [events, artifacts] = await Promise.all([
      cm.getTaskEvents(state.selectedTaskId),
      cm.listArtifacts(state.selectedTaskId),
    ]);
    state.events = events;
    state.artifacts = artifacts;
    state.status = "Connected";
  } catch (error) {
    state.status = error instanceof Error ? error.message : "Unable to load task";
    state.events = [];
    state.artifacts = [];
  }
  if (shouldRender) {
    render();
  }
}

function escapeHtml(value: unknown): string {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttribute(value: unknown): string {
  return escapeHtml(value);
}

function escapeClass(value: unknown): string {
  return String(value || "unknown").replace(/[^a-zA-Z0-9_-]/g, "-");
}

function formatBytes(value: unknown): string {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "";
  }
  if (value < 1024) {
    return `${value} B`;
  }
  if (value < 1024 * 1024) {
    return `${(value / 1024).toFixed(1)} KB`;
  }
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

render();
void load();
