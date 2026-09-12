import { afterEach, expect, test } from "bun:test";
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { LocalRuntimeControl, openLocalRuntime, RuntimeDatabase, type Principal } from "../src";
import { event, eventConfig, signed } from "./helpers/feishu-events";
import { digest } from "../src/value";
import { directoryIdentity } from "../src/providers/native-manifest";

const roots: string[] = [];
afterEach(() => { for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true }); });
function fixture() {
  const root = mkdtempSync(join(tmpdir(), "cm-local-control-")); roots.push(root);
  const state = join(root, "state"), workspace = join(root, "workspace"), data = join(root, "native-data");
  mkdirSync(state, { mode: 0o700 }); mkdirSync(workspace);
  const config = { schema_version: "controlmesh.local_runtime.v1", mode: "candidate", state_root: state, principal_id: "operator", device_id: "local",
    source: { command_origin: "human_request", origin: "user", source_scope: "local_foreground", transport: "terminal" },
    opencode: { executable: "/missing/opencode", model: "fixture/model", cli_version: "1.18.29", native_configuration: {}, environment: { XDG_DATA_HOME: data, XDG_CACHE_HOME: join(root, "native-cache") },
      container: { docker: "/missing/docker", socket: "/missing/docker.sock", image_id: `sha256:${"a".repeat(64)}`, node_executable: "/usr/local/bin/node" } },
    workspace: { directory: workspace, read_files: [], required_reads: [] } };
  const path = join(root, "control.json"); writeFileSync(path, JSON.stringify(config), { mode: 0o600 });
  return { root, state, workspace, data, path, config };
}

test("recovery status remains readable without provider credentials and cannot accept caller-supplied authority", async () => {
  const f = fixture(), owned = openLocalRuntime(f.path);
  const control = new LocalRuntimeControl(owned.runtime, undefined, owned.submissionIdentity, undefined, undefined, owned.recovery);
  const actor: Principal = { id: "operator", device_id: "local", origin: "human_request", scopes: ["task:read", "task:execute", "task:reconcile"] };
  try {
    const created = owned.runtime.submit("create", { task_id: "pending", chat_id: "fixture", status: "waiting", repo_root: f.workspace, provider: "opencode", model: "fixture/model", prompt: "fixture" }, { chat_id: "fixture" });
    const kernel = owned.runtime.kernel, lease = kernel.claim(actor, "claim", "pending", created.revision, 60000);
    kernel.start(actor, "start", lease);
    kernel.dispatchEffect(actor, "dispatch", lease, "effect", {}, { schema_version: "controlmesh.native_dispatch.v1", task_digest: digest("fixture"),
      binding: { provider: "opencode", cli_version: "1.18.29" }, native_store_id: digest("unavailable"), baseline: null,
      directory: directoryIdentity(f.workspace), worktree: directoryIdentity(f.workspace), files: [], required_reads: [],
      permission_evidence: { agent: "fixture", data_home: f.data, resolved: {}, digest: digest("unverified") } });
    kernel.recordEffectObservation(actor, "observe", lease, "effect", { terminal: false }); kernel.markUnknown(actor, "unknown", lease, "completion_missing");
    const revision = kernel.inspect(actor, "pending").revision;
    const response = await control.handle({ id: "inspect", op: "inspect_reconciliation", task_id: "pending", expected_revision: revision, effect_id: "effect" });
    expect(response).toMatchObject({ ok: true, result: { effect_id: "effect", episode_id: lease.episode_id } });
    expect(existsSync(f.data)).toBe(false);
    expect(await control.handle({ id: "forged", op: "reconcile_task", task_id: "pending", expected_revision: revision,
      candidate: { ...response.result as object, workspace_write: { roots: ["/"] } } })).toMatchObject({ ok: false, error: "invalid_reconciliation_binding" });
    expect(kernel.inspect(actor, "pending").task.status).toBe("stale"); expect(existsSync(f.data)).toBe(false);
  } finally { await owned.close(); }
});

test("private ingress preserves the group approval floor before creating native state or probing a model", async () => {
  const f = fixture(), verification = join(f.root, "verification.json");
  writeFileSync(verification, JSON.stringify({ app_id: eventConfig.app_id, verification_token: eventConfig.verification_token, encrypt_key: eventConfig.encrypt_key }), { mode: 0o600 });
  writeFileSync(f.path, JSON.stringify({ ...f.config, source: { ...f.config.source, transport: "fs" },
    delivery: { kind: "feishu_text", adapter_id: "selected-app", app_id: eventConfig.app_id, token_file: join(f.root, "unused-token.json") },
    inbound: { credentials_file: verification, allowed_senders: eventConfig.allowed_senders, allowed_chats: eventConfig.allowed_chats, bot_open_id: eventConfig.bot_open_id } }));
  const owned = openLocalRuntime(f.path), control = new LocalRuntimeControl(owned.runtime, owned.deliveries, owned.submissionIdentity, owned.inbound);
  try {
    const body = event("@_user_1 work", "group", true); body.event.message.mentions = [{ id: { open_id: "ou_bot" }, key: "@_user_1" }];
    const packet = signed(body), receipt = owned.inbound!.inbox.receive(packet.headers, packet.bytes);
    expect(receipt).toMatchObject({ accepted: true });
    expect(await control.handle({ id: "drain", op: "drain_inbound" })).toMatchObject({ ok: true,
      result: { blocked: 1, applied: 0, blocked_items: [{ reason: "controller_approval_unavailable" }] } });
    for (const table of ["tasks", "provider_checks", "local_runs"]) expect(owned.runtime.kernel.db.sql.query(`SELECT COUNT(*) AS n FROM ${table}`).get()).toEqual({ n: 0 });
    expect(existsSync(f.data)).toBe(false);
    expect(await control.handle({ id: "override", op: "start_inbound", port: 9000 })).toMatchObject({ ok: false, error: "unexpected_local_request_field" });
    writeFileSync(verification, JSON.stringify({ app_id: "cli_other", verification_token: "changed", encrypt_key: "changed" }));
    expect(() => owned.inbound!.inbox.receive(packet.headers, packet.bytes)).toThrow("feishu_event_configuration_changed");
  } finally { await owned.close(); }
});

test("the standalone headless Feishu process accepts verification, stops cleanly and never starts an Agent", async () => {
  const f = fixture(), verification = join(f.root, "verification.json");
  writeFileSync(verification, JSON.stringify({ app_id: eventConfig.app_id, verification_token: eventConfig.verification_token, encrypt_key: eventConfig.encrypt_key }), { mode: 0o600 });
  writeFileSync(f.path, JSON.stringify({ ...f.config, source: { ...f.config.source, transport: "fs" },
    delivery: { kind: "feishu_text", adapter_id: "selected-app", app_id: eventConfig.app_id, token_file: join(f.root, "unused-token.json") },
    inbound: { credentials_file: verification, allowed_senders: eventConfig.allowed_senders, allowed_chats: eventConfig.allowed_chats } }));
  const child = Bun.spawn([process.execPath, join(import.meta.dir, "../scripts/serve-feishu.ts"), f.path], { stdin: "ignore", stdout: "pipe", stderr: "pipe" });
  const deadline = setTimeout(() => { if (child.exitCode === null) child.kill("SIGTERM"); }, 10_000);
  const reader = child.stdout.getReader(), stderr = new Response(child.stderr).text();
  try {
    let line = "";
    while (!line.includes("\n")) { const part = await reader.read(); if (part.done) break; line += new TextDecoder().decode(part.value); }
    const listener = JSON.parse(line.trim()); expect(listener).toMatchObject({ status: "listening", hostname: "127.0.0.1", path: "/feishu/events" });
    const response = await fetch(`http://${listener.hostname}:${listener.port}${listener.path}`, { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ type: "url_verification", token: eventConfig.verification_token, challenge: "headless" }) });
    expect(await response.json()).toEqual({ challenge: "headless" });
    child.kill("SIGTERM"); expect(await child.exited).toBe(0); expect(await stderr).toBe("");
    expect(existsSync(f.data)).toBe(false);
    const db = new RuntimeDatabase(join(f.state, "runtime.sqlite"));
    try { for (const table of ["tasks", "provider_checks", "feishu_inbox"]) expect(db.sql.query(`SELECT COUNT(*) AS n FROM ${table}`).get()).toEqual({ n: 0 }); } finally { db.close(); }
  } finally {
    clearTimeout(deadline);
    if (child.exitCode === null) child.kill("SIGTERM");
    await child.exited; await reader.cancel(); await stderr;
  }
}, 15_000);

test("local status and task submission work without native credentials and cannot issue task-body authority", async () => {
  const f = fixture(), owned = openLocalRuntime(f.path), control = new LocalRuntimeControl(owned.runtime);
  try {
    const task = { task_id: "a", status: "waiting", chat_id: "local", prompt: "fixture" };
    expect(await control.handle({ id: "submit", op: "submit", task })).toMatchObject({ ok: true });
    expect(await control.handle({ id: "inspect", op: "inspect_task", task_id: "a" })).toMatchObject({ ok: true, result: { task: { status: "waiting" } } });
    expect(await control.handle({ id: "bad-source", op: "inspect_task", task_id: "a", origin: "human_request" })).toMatchObject({ ok: false, error: "unexpected_local_request_field" });
    expect(await control.handle({ id: "bad-grant", op: "submit", task: { ...task, task_id: "b", tool_grant: {} } })).toMatchObject({ ok: false, error: "task_body_cannot_issue_authority" });
    const sent = await control.handle({ id: "tell", op: "tell", task_id: "a", text: "Queued handoff" });
    const messageId = (sent.result as { message_id: string }).message_id;
    expect(await control.handle({ id: "inspect-mail", op: "inspect_message", task_id: "a", message_id: messageId }))
      .toMatchObject({ ok: true, result: { status: "pending", origin: "human_request" } });
    expect(await control.handle({ id: "mail-status", op: "mailbox_status", task_id: "a" })).toMatchObject({ ok: true, result: { pending_count: 1 } });
    expect(existsSync(f.data)).toBe(false);
    expect(owned.runtime.kernel.db.sql.query("SELECT COUNT(*) AS n FROM provider_checks").get()).toEqual({ n: 0 });
    expect(owned.runtime.kernel.db.sql.query("SELECT COUNT(*) AS n FROM local_runs").get()).toEqual({ n: 0 });
  } finally { await owned.close(); }
});

test("private configuration is explicit, legacy state is refused, and config replacement revokes admission", async () => {
  const f = fixture(); chmodSync(f.path, 0o644);
  expect(() => openLocalRuntime(f.path)).toThrow("private_runtime_config_required"); chmodSync(f.path, 0o600);
  writeFileSync(join(f.state, "tasks.json"), '{"tasks":[]}');
  expect(() => openLocalRuntime(f.path)).toThrow("legacy_runtime_state_forbidden"); rmSync(join(f.state, "tasks.json"));
  const owned = openLocalRuntime(f.path);
  try {
    writeFileSync(f.path, JSON.stringify({ ...f.config, principal_id: "changed" }), { mode: 0o600 });
    expect(() => owned.runtime.queueStatus()).toThrow("runtime_configuration_changed");
  } finally { await owned.close(); }
});

test("configured delivery stays independent of native startup and an expired selected-app token blocks before HTTP", async () => {
  const f = fixture(), tokenPath = join(f.root, "delivery-token.json");
  writeFileSync(tokenPath, JSON.stringify({ app_id: "cli_fixture", tenant_access_token: "fixture_expired", expires_at: 1 }), { mode: 0o600 });
  writeFileSync(f.path, JSON.stringify({ ...f.config, source: { ...f.config.source, transport: "fs" },
    delivery: { kind: "feishu_text", adapter_id: "selected-app", app_id: "cli_fixture", token_file: tokenPath } }));
  const owned = openLocalRuntime(f.path), control = new LocalRuntimeControl(owned.runtime, owned.deliveries);
  try {
    expect(owned.deliveries?.status()).toEqual({ pending: 0, dispatching: 0, sent: 0, unknown: 0, blocked: 0 });
    expect(await control.handle({ id: "submit", op: "submit", task: { task_id: "a", status: "waiting", chat_id: "oc_fixture" } })).toMatchObject({ ok: true });
    expect(await control.handle({ id: "bind", op: "bind_delivery", task_id: "a", expected_revision: 1, adapter_id: "selected-app" })).toMatchObject({ ok: true });
    const principal: Principal = { id: "operator", device_id: "local", origin: "internal", scopes: ["task:read", "task:execute"] };
    const kernel = owned.runtime.kernel, lease = kernel.claim(principal, "claim", "a", 1, 5000);
    kernel.start(principal, "start", lease); kernel.finish(principal, "finish", lease, "done", { delivery_text: "fixture summary" });
    expect(await control.handle({ id: "deliver", op: "drain_deliveries" })).toMatchObject({ ok: true, result: { blocked: 1, sent: 0 } });
    expect(owned.deliveries!.list("a")[0]).toMatchObject({ reason: "feishu_token_unavailable", observed_receipt: null });
    expect(kernel.db.sql.query("SELECT COUNT(*) AS n FROM provider_checks").get()).toEqual({ n: 0 }); expect(existsSync(f.data)).toBe(false);
  } finally { await owned.close(); }
});

test("actual stdio entrypoint handles bounded commands and preserves request IDs without a provider call", async () => {
  const f = fixture();
  const child = Bun.spawn([process.execPath, join(import.meta.dir, "../scripts/local-runtime.ts"), f.path], { stdin: "pipe", stdout: "pipe", stderr: "pipe" });
  child.stdin.write([
    { id: "create", op: "submit", task: { task_id: "a", status: "waiting", chat_id: "local", prompt: "fixture" } },
    { id: "inspect", op: "inspect_task", task_id: "a" },
    { id: "drain", op: "drain" },
  ].map(value => JSON.stringify(value)).join("\n") + "\n");
  child.stdin.end();
  const [stdout, stderr, code] = await Promise.all([new Response(child.stdout).text(), new Response(child.stderr).text(), child.exited]);
  expect({ stderr, code }).toEqual({ stderr: "", code: 0 });
  const rows = stdout.trim().split("\n").map(line => JSON.parse(line));
  expect(rows.map(row => row.id).sort()).toEqual(["create", "drain", "inspect"]);
  expect(rows.every(row => row.ok)).toBe(true); expect(existsSync(f.data)).toBe(false);
  const db = new RuntimeDatabase(join(f.state, "runtime.sqlite"));
  try { expect(db.sql.query("SELECT COUNT(*) AS n FROM provider_checks").get()).toEqual({ n: 0 }); } finally { db.close(); }
}, 10_000);

test("schema eight upgrades without losing tasks or queued messages and without executing them", async () => {
  const f = fixture(), first = openLocalRuntime(f.path);
  first.runtime.submit("create", { task_id: "a", status: "waiting", chat_id: "local" }, { chat_id: "local" });
  const sent = first.runtime.tell("note", "a", "Survive upgrade");
  await first.close();
  const previous = new RuntimeDatabase(join(f.state, "runtime.sqlite"));
  previous.sql.exec("DROP TABLE topology_artifact_publications; DROP TABLE device_artifact_files; DROP TABLE topology_native_inputs; DROP TABLE topology_device_runs; ALTER TABLE topology_tasks DROP COLUMN execution_source; DROP TABLE topology_schedule_members; DROP TABLE topology_schedules; ALTER TABLE topology_tasks DROP COLUMN kind; DROP TABLE topology_runs; ALTER TABLE topology_tasks DROP COLUMN execution_id; DROP TABLE topology_completions; DROP TABLE topology_controls; DROP TABLE topology_task_history; DROP TABLE topology_tasks; DROP TABLE team_topologies; DROP TABLE team_phases; DROP TABLE device_scheduled_work; DROP TABLE device_scheduler_leases; DROP TABLE device_assignment_generations; DROP TABLE device_native_adoptions; DROP TABLE command_reservations; DROP TABLE feishu_conversations; DROP TABLE feishu_event_aliases; DROP TABLE feishu_inbox; DROP TABLE transport_receipts; DROP TABLE delivery_outbox; DROP TABLE delivery_routes; DROP TABLE native_agent_deliveries; DROP TABLE native_agent_calls; DROP TABLE native_mailbox_deliveries; PRAGMA user_version=8"); previous.close();
  const restored = openLocalRuntime(f.path);
  try {
    expect(restored.runtime.kernel.db.sql.query("PRAGMA user_version").get()).toEqual({ user_version: 28 });
    expect(restored.runtime.inspectTask("a").task.status).toBe("waiting");
    expect(restored.runtime.inspectMessage("a", sent.message_id).payload).toEqual({ text: "Survive upgrade" });
    expect(restored.runtime.mailboxStatus("a")).toEqual({ pending_count: 1 });
    expect(existsSync(f.data)).toBe(false);
  } finally { await restored.close(); }
});

test("private startup binds the configured reply thread without reading credentials or launching a provider", async () => {
  const f = fixture();
  writeFileSync(f.path, JSON.stringify({ ...f.config, source: { ...f.config.source, transport: "fs" },
    delivery: { kind: "feishu_text", adapter_id: "selected-app", app_id: "cli_fixture", app_credentials_file: join(f.root, "not-created.json"),
      replies: { a: { chat_id: "oc_fixture", message_id: "om_trigger", thread_id: "th_fixture", reply_in_thread: true } } } }));
  const owned = openLocalRuntime(f.path), control = new LocalRuntimeControl(owned.runtime, owned.deliveries, owned.submissionIdentity);
  try {
    expect(await control.handle({ id: "create", op: "submit", task: { task_id: "a", status: "waiting", chat_id: "oc_fixture" } })).toMatchObject({ ok: true });
    expect(owned.runtime.inspectTask("a").task).toMatchObject({ thread_id: "th_fixture", tool_grant: { reply_thread: "th_fixture" } });
    expect(await control.handle({ id: "bind", op: "bind_delivery", task_id: "a", expected_revision: 1, adapter_id: "selected-app" })).toMatchObject({ ok: true });
    expect(existsSync(f.data)).toBe(false); expect(owned.deliveries!.status().pending).toBe(0);
  } finally { await owned.close(); }
});

test("SIGTERM in the real stdio entrypoint aborts delivery before the HTTP timeout and preserves its unknown outcome", async () => {
  const f = fixture(), tokenPath = join(f.root, "token.json"), preload = join(f.root, "loopback-preload.ts");
  writeFileSync(tokenPath, JSON.stringify({ app_id: "cli_fixture", tenant_access_token: "fixture_token", expires_at: Date.now() + 60_000 }), { mode: 0o600 });
  writeFileSync(f.path, JSON.stringify({ ...f.config, source: { ...f.config.source, transport: "fs" },
    delivery: { kind: "feishu_text", adapter_id: "selected-app", app_id: "cli_fixture", token_file: tokenPath } }));
  const owned = openLocalRuntime(f.path);
  owned.runtime.submit("create", { task_id: "a", chat_id: "oc_fixture", status: "waiting" }, { chat_id: "oc_fixture" });
  owned.deliveries!.bindTask("bind", "a", 1, "selected-app");
  const principal: Principal = { id: "operator", device_id: "local", origin: "internal", scopes: ["task:read", "task:execute"] };
  const lease = owned.runtime.kernel.claim(principal, "claim", "a", 1, 5000);
  owned.runtime.kernel.start(principal, "start", lease); owned.runtime.kernel.finish(principal, "finish", lease, "done", { delivery_text: "fixture" });
  await owned.close();
  let observed!: () => void, release!: () => void;
  const received = new Promise<void>(resolve => { observed = resolve; }), held = new Promise<void>(resolve => { release = resolve; });
  const server = Bun.serve({ hostname: "127.0.0.1", port: 0, async fetch(request) {
    expect(request.method).toBe("POST"); expect(request.headers.get("authorization")).toBe("Bearer fixture_token");
    await request.json(); observed(); await held; return Response.json({ code: 0 });
  } });
  writeFileSync(preload, `const real = globalThis.fetch; globalThis.fetch = ((input, init) => {
    const url = new URL(String(input)); if (url.origin !== "https://open.feishu.cn") throw new Error("unexpected_test_origin");
    return real(${JSON.stringify(server.url.origin)} + url.pathname + url.search, init);
  }) as typeof fetch;`);
  const child = Bun.spawn([process.execPath, "--preload", preload, join(import.meta.dir, "../scripts/local-runtime.ts"), f.path],
    { stdin: "pipe", stdout: "pipe", stderr: "pipe" });
  const output = Promise.all([new Response(child.stdout).text(), new Response(child.stderr).text()]);
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    child.stdin.write(JSON.stringify({ id: "drain", op: "drain_deliveries" }) + "\n");
    await Promise.race([received, new Promise((_, reject) => { timer = setTimeout(() => reject(new Error("fixture_start_timeout")), 3000); })]);
    clearTimeout(timer); expect(child.pid).toBeGreaterThan(1); expect(child.pid).not.toBe(process.pid); child.kill("SIGTERM");
    await Promise.race([child.exited, new Promise((_, reject) => { timer = setTimeout(() => reject(new Error("shutdown_did_not_abort_delivery")), 3000); })]);
    clearTimeout(timer); const [stdout, stderr] = await output;
    expect(await child.exited).toBe(0); expect(stderr).toBe("");
    expect(JSON.parse(stdout.trim())).toMatchObject({ id: "drain", ok: false, error: "delivery_stopping" });
    const db = new RuntimeDatabase(join(f.state, "runtime.sqlite"));
    try { expect(db.sql.query("SELECT state FROM delivery_outbox").get()).toEqual({ state: "unknown" }); }
    finally { db.close(); }
  } finally {
    clearTimeout(timer); release(); server.stop(true);
    if (child.exitCode === null) { expect(child.pid).toBeGreaterThan(1); expect(child.pid).not.toBe(process.pid); child.kill("SIGKILL"); }
    await child.exited; await output;
  }
}, 10_000);

test("stdio rejects oversized commands and never treats their tail as another request", async () => {
  const f = fixture();
  const child = Bun.spawn([process.execPath, join(import.meta.dir, "../scripts/local-runtime.ts"), f.path], { stdin: "pipe", stdout: "pipe", stderr: "pipe" });
  child.stdin.write("x".repeat(65_537) + "\n"); child.stdin.end();
  const [stdout, stderr, code] = await Promise.all([new Response(child.stdout).text(), new Response(child.stderr).text(), child.exited]);
  expect(stdout).toBe(""); expect(code).toBe(2); expect(stderr).toMatch(/local_control_backpressure|local_request_too_large/);
  expect(readFileSync(f.path, "utf8")).toBe(JSON.stringify(f.config));
}, 10_000);

test("normal local configuration exposes paused schedules without provider credentials", async () => {
  const f = fixture();
  writeFileSync(f.path, JSON.stringify({ ...f.config, topology_scheduler: { auto_start: false, keep_alive: false, interval_ms: 100 } }));
  const owned = openLocalRuntime(f.path), control = new LocalRuntimeControl(owned.runtime, owned.deliveries, owned.submissionIdentity, owned.inbound, owned.specmesh, owned.recovery, owned.history, owned.scheduler);
  try {
    expect(owned.scheduler?.status()).toEqual({ running: false, stopping: false, error: null });
    for (const id of ["root", "worker", "reviewer"])
      expect(await control.handle({ id: `submit-${id}`, op: "submit", task: { task_id: id, chat_id: "fixture", status: "waiting", provider: "opencode", prompt: "authorized initial input", repo_root: f.workspace } })).toMatchObject({ ok: true });
    const plan = { schema_version: "controlmesh.topology_schedule.v1", root_task_id: "root", nodes: [{ task_id: "root", topology: "pipeline", worker_roles: ["worker"], controller_role: "reviewer",
      roles: ["worker", "reviewer"].map(role => ({ role, task_id: role, resume_prompt: "continue" })) }] };
    expect(await control.handle({ id: "register", op: "register_schedule", plan })).toMatchObject({ ok: true, result: { mode: "paused" } });
    expect(await control.handle({ id: "drain", op: "drain_schedules" })).toMatchObject({ ok: true }); expect(existsSync(f.data)).toBe(false);
    expect(await control.handle({ id: "activate", op: "activate_schedule", root_task_id: "root", expected_revision: 1 })).toMatchObject({ ok: true });
    await control.handle({ id: "advance", op: "drain_schedules" });
    expect(await control.handle({ id: "inspect", op: "inspect_schedule", root_task_id: "root" })).toMatchObject({ ok: true, result: { mode: "blocked" } });
    expect(existsSync(f.data)).toBe(false);
    writeFileSync(f.path, JSON.stringify({ ...f.config, topology_scheduler: { auto_start: false, keep_alive: false, interval_ms: 200 } }));
    expect(await control.handle({ id: "changed", op: "inspect_schedule", root_task_id: "root" })).toMatchObject({ ok: false, error: "runtime_configuration_changed" });
  } finally { await owned.close(); }
});

test("the actual local CLI keeps a configured scheduler alive after EOF and stops on SIGTERM", async () => {
  const f = fixture();
  writeFileSync(f.path, JSON.stringify({ ...f.config, topology_scheduler: { auto_start: true, keep_alive: true, interval_ms: 100 } }));
  const child = Bun.spawn([process.execPath, join(import.meta.dir, "../scripts/local-runtime.ts"), f.path], { stdin: "pipe", stdout: "pipe", stderr: "pipe" });
  const deadline = setTimeout(() => { if (child.exitCode === null) child.kill("SIGTERM"); }, 8000);
  const stderr = new Response(child.stderr).text(), reader = child.stdout.getReader();
  try {
    child.stdin.write(JSON.stringify({ id: "status", op: "scheduler_status" }) + "\n"); child.stdin.end();
    let line = "";
    while (!line.includes("\n")) { const part = await reader.read(); if (part.done) break; line += new TextDecoder().decode(part.value); }
    expect(JSON.parse(line.trim())).toMatchObject({ id: "status", ok: true, result: { running: true } });
    await Bun.sleep(150); expect(child.exitCode).toBeNull(); expect(existsSync(f.data)).toBe(false);
    child.kill("SIGTERM"); expect(await child.exited).toBe(0); expect(await stderr).toBe("");
  } finally { clearTimeout(deadline); if (child.exitCode === null) child.kill("SIGTERM"); await child.exited; reader.releaseLock(); }
});

test("scheduler configuration is explicit and rejects unknown or malformed fields", async () => {
  const f = fixture();
  for (const settings of [{ auto_start: "yes", keep_alive: false }, { auto_start: false, keep_alive: false, interval_ms: 1 },
    { auto_start: false, keep_alive: false, grant: "all" }, { auto_start: true, keep_alive: false, artifact_files: ["../escape"] }]) {
    writeFileSync(f.path, JSON.stringify({ ...f.config, topology_scheduler: settings })); expect(() => openLocalRuntime(f.path)).toThrow();
  }
  writeFileSync(f.path, JSON.stringify(f.config)); const owned = openLocalRuntime(f.path);
  try {
    expect(owned.scheduler).toBeUndefined();
    expect(await new LocalRuntimeControl(owned.runtime).handle({ id: "start", op: "start_scheduler" })).toMatchObject({ ok: false, error: "topology_scheduler_not_configured" });
  } finally { await owned.close(); }
});
