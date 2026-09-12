import { afterEach, expect, test } from "bun:test";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { RuntimeKernel, type Principal } from "../src/kernel";
import { RuntimeDatabase } from "../src/database";
import { WorkspaceStage } from "../src/workspace-stage";
import { NativeWorkspaceFiles, nativeWorkspaceTools, type WorkspaceFilesConfiguration } from "../src/providers/native-workspace-files";
import { NativeAgentChannel } from "../src/providers/native-agent-broker";
import { prepareNativeAgentConfiguration } from "../src/providers/native-agent-profile";
import { canonical, digest } from "../src/value";
import { NativeMcpTestClient } from "./helpers/native-mcp-client";

const cleanup: (() => void | Promise<void>)[] = [];
afterEach(async () => { for (const close of cleanup.splice(0).reverse()) await close(); });
const actor: Principal = { id: "operator", device_id: "desktop", origin: "human_request", scopes: ["task:create", "task:execute", "task:read", "task:cancel"] };
function fixture(staged = true, content = "original current fact\n") {
  const root = mkdtempSync(join(tmpdir(), "cm-workspace-tools-")); cleanup.push(() => rmSync(root, { recursive: true, force: true }));
  const workspace = join(root, "project"), state = join(root, "state"), journal = join(root, "receipts");
  for (const dir of [workspace, state, journal]) mkdirSync(dir, { mode: 0o700 });
  const allowed = join(workspace, "PROJECT.md"), ungranted = join(workspace, "ungranted.txt");
  writeFileSync(allowed, content); writeFileSync(ungranted, "not granted");
  const db = new RuntimeDatabase(":memory:"); cleanup.push(() => db.close());
  const kernel = new RuntimeKernel(db); kernel.submit(actor, "create", { task_id: "task", status: "waiting", chat_id: "fixture" });
  const lease = kernel.claim(actor, "claim", "task", 1, 300000); kernel.start(actor, "start", lease);
  const authority = <T>(operation: () => T) => kernel.withLease(actor, lease, operation);
  const binding = digest({ task: "task", effect: "effect" });
  const stage = staged ? WorkspaceStage.create(state, workspace, [workspace], binding, authority) : undefined;
  const config: WorkspaceFilesConfiguration = { workspace, read_files: [allowed], tools: staged ? nativeWorkspaceTools : ["controlmesh_read_file"], journal_directory: journal, binding_digest: binding, stage };
  let check = () => {};
  const files = new NativeWorkspaceFiles(config, authority, () => check());
  kernel.dispatchEffect(actor, "dispatch", lease, "effect", {}, { workspace_tools: files.scope });
  const proof: { tool: string; input: Record<string, unknown>; output: string }[] = [];
  const call = (tool: string, input: Record<string, unknown>) => {
    const response = files.call(`controlmesh_${tool}`, input); proof.push({ tool: `controlmesh_${tool}`, input, output: canonical(response) }); return response;
  };
  return { root, workspace, state, journal, allowed, ungranted, kernel, db, lease, authority, config, files, stage, proof, call, setCheck: (fn: () => void) => { check = fn; } };
}
test("missing write preconditions explain corrective input without inventing a content conflict or writing", async () => {
  const f = fixture(), config = prepareNativeAgentConfiguration(join(f.root, "ipc"), Bun.which("node")!, "task", [], null, "workspace.v1");
  const broker = new NativeAgentChannel(f.lease, config, () => {}, { assertDispatched: () => f.kernel.withLease(actor, f.lease, () => {}), call: async (tool, input) => f.files.call(tool, input) });
  cleanup.push(() => broker.close()); await broker.start();
  const client = new NativeMcpTestClient(broker.command); cleanup.push(() => client.close()); await client.initialize();
  const input = { request_id: "missing", path: "new.txt", content: "after" };
  const response = await client.tool("write_file", input);
  expect(response.result?.isError).toBe(true);
  const failure = JSON.parse(response.result!.content![0].text);
  expect(failure).toMatchObject({ ok: false, error: "workspace_tool_expected_sha256_required" });
  expect(failure.hint).toContain("null"); expect(failure.hint).toContain("new request_id");
  expect(existsSync(join(f.stage!.fileScope().tree, "new.txt"))).toBe(false);
  const reopened = new NativeWorkspaceFiles(f.config, f.authority, () => {});
  expect(reopened.call("controlmesh_write_file", input)).toEqual(failure);
  expect(() => reopened.call("controlmesh_write_file", { ...input, expected_sha256: null })).toThrow("idempotency_conflict");
  expect(reopened.call("controlmesh_write_file", { ...input, request_id: "corrected", expected_sha256: null })).toMatchObject({ ok: true });
  expect(readFileSync(join(f.stage!.fileScope().tree, "new.txt"), "utf8")).toBe("after");
  expect(reopened.call("controlmesh_write_file", { ...input, request_id: "existing", expected_sha256: null })).toMatchObject({ ok: false, error: "workspace_tool_content_changed" });
  expect(existsSync(join(f.workspace, "new.txt"))).toBe(false);
});
test("explicit missing sentinel creates once and never overwrites an existing file", () => {
  const f = fixture(), input = { request_id: "create", path: "new.txt", expected_sha256: "missing", content: "first" };
  const created = f.call("write_file", input); expect(created).toMatchObject({ ok: true });
  const reopened = new NativeWorkspaceFiles(f.config, f.authority, () => {});
  expect(reopened.call("controlmesh_write_file", input)).toEqual(created);
  for (const expected_sha256 of ["missing", null, "not-a-hash", ""]) {
    expect(f.call("write_file", { ...input, request_id: `reject-${String(expected_sha256) || "empty"}`, expected_sha256, content: "overwrite" }))
      .toMatchObject({ ok: false, error: "workspace_tool_content_changed" });
  }
  expect(readFileSync(join(f.stage!.fileScope().tree, "new.txt"), "utf8")).toBe("first");
  const read = f.call("read_file", { request_id: "read", path: "new.txt" });
  expect(f.call("write_file", { ...input, request_id: "replace", expected_sha256: read.sha256, content: "second" })).toMatchObject({ ok: true });
  expect(readFileSync(join(f.stage!.fileScope().tree, "new.txt"), "utf8")).toBe("second");
  expect(existsSync(join(f.workspace, "new.txt"))).toBe(false);
  expect(f.files.verify(f.proof, []).written_files).toEqual([join(f.workspace, "new.txt")]);
  const substituted = f.proof.map((call, index) => index === 0 ? { ...call, input: { ...call.input, expected_sha256: null } } : call);
  expect(() => f.files.verify(substituted, [])).toThrow("workspace_tool_call_unproven");
});

test("completion requires current-turn evidence and optional exact content, not existing files", () => {
  const f = fixture(), requirement = { schema_version: "controlmesh.task_completion.v1", files: [{ path: "new.txt", mode: "write" }] };
  expect(() => f.files.verifyCompletion(requirement, f.files.verify([], []))).toThrow("task_completion_evidence_missing");
  const readExisting = { ...requirement, files: [{ path: "PROJECT.md", mode: "read" }] };
  expect(() => f.files.verifyCompletion(readExisting, f.files.verify([], []))).toThrow("task_completion_evidence_missing");
  f.call("read_file", { request_id: "context", path: "PROJECT.md" });
  expect(f.files.verifyCompletion(readExisting, f.files.verify(f.proof, []))).toMatchObject({ files: [{ path: "PROJECT.md", mode: "read" }] });
  f.call("write_file", { request_id: "create", path: "new.txt", expected_sha256: "missing", content: "output" });
  const proof = f.files.verify(f.proof, []), verified = f.files.verifyCompletion(requirement, proof)!;
  expect(verified).toMatchObject({ files: [{ path: "new.txt", mode: "write" }] });
  expect(() => f.files.verifyCompletion({ ...requirement, files: [{ path: "new.txt", mode: "write", sha256: "0".repeat(64) }] }, proof)).toThrow("task_completion_content_mismatch");
  for (const path of ["../new.txt", "/new.txt", "a/../new.txt", "./new.txt", ".git/config", "a//b"]) {
    expect(() => f.files.verifyCompletion({ ...requirement, files: [{ path, mode: "write" }] }, proof)).toThrow("invalid_completion_path");
  }
});

test("explicit file scope denies ungranted reads and does not grant writes to a read-only owner", () => {
  const f = fixture(false);
  expect(f.call("read_file", { request_id: "allowed", path: "PROJECT.md" })).toMatchObject({ ok: true, content: "original current fact\n", eof: true });
  expect(f.call("read_file", { request_id: "denied", path: "ungranted.txt" })).toMatchObject({ ok: false, error: "workspace_tool_path_not_granted" });
  expect(f.call("write_file", { request_id: "write", path: "PROJECT.md", expected_sha256: null, content: "bad" })).toMatchObject({ ok: false, error: "workspace_tool_not_granted" });
  expect(f.files.verify(f.proof, [f.allowed]).read_files).toEqual([f.allowed]);
  expect(readFileSync(f.allowed, "utf8")).toBe("original current fact\n");
});
test("CAS writes and exact edits stay staged; native evidence and final bytes bind publication", () => {
  const f = fixture();
  const read = f.call("read_file", { request_id: "read", path: "PROJECT.md" });
  const edited = f.call("edit_file", { request_id: "edit", path: "PROJECT.md", expected_sha256: read.sha256, old_text: "original", new_text: "updated" });
  expect(edited).toMatchObject({ ok: true, staged: true }); expect(readFileSync(f.allowed, "utf8")).toBe("original current fact\n");
  expect(f.call("edit_file", { request_id: "stale", path: "PROJECT.md", expected_sha256: read.sha256, old_text: "updated", new_text: "lost" })).toMatchObject({ ok: false, error: "workspace_tool_content_changed" });
  expect(() => f.files.verify(f.proof, [f.allowed])).toThrow("workspace_tool_required_read_missing");
  f.call("read_file", { request_id: "reread", path: "PROJECT.md" });
  f.call("write_file", { request_id: "new", path: "src/nested/new.ts", expected_sha256: null, content: "export const n = 1;\n" });
  const verified = f.files.verify(f.proof, [f.allowed]); expect(verified.written_files).toEqual([f.allowed, join(f.workspace, "src/nested/new.ts")]);
  const proposal = f.stage!.seal(f.authority); f.stage!.promote(f.authority, proposal.proposal_digest);
  expect(readFileSync(f.allowed, "utf8")).toBe("updated current fact\n"); expect(readFileSync(join(f.workspace, "src/nested/new.ts"), "utf8")).toBe("export const n = 1;\n");
});
test("same request returns its original receipt after reopening; changed bodies and scope reuse reject", () => {
  const f = fixture(), input = { request_id: "new", path: "new.txt", expected_sha256: null, content: "one" };
  const first = f.call("write_file", input), staged = join(f.stage!.fileScope().tree, "new.txt"), before = statSync(staged).mtimeMs;
  const reopened = new NativeWorkspaceFiles({ ...f.config, stage: WorkspaceStage.open(f.stage!.path, f.stage!.reference()) }, f.authority, () => {});
  expect(reopened.call("controlmesh_write_file", input)).toEqual(first); expect(statSync(staged).mtimeMs).toBe(before);
  expect(() => reopened.call("controlmesh_write_file", { ...input, content: "other" })).toThrow("idempotency_conflict");
  expect(() => new NativeWorkspaceFiles({ ...f.config, binding_digest: digest("different") }, f.authority, () => {})).toThrow("workspace_tool_journal_scope_changed");
  expect(reopened.verify(f.proof, []).written_files).toEqual([join(f.workspace, "new.txt")]);
});
test("UTF-8 pages preserve BOM and require complete same-revision coverage", () => {
  const value = "\uFEFF" + "雪🌱".repeat(800), f = fixture(false, value);
  let response = f.call("read_file", { request_id: "first", path: f.allowed });
  expect(response.eof).toBe(false); expect(String(response.content).startsWith("\uFEFF")).toBe(true);
  expect(() => f.files.verify(f.proof, [f.allowed])).toThrow("workspace_tool_required_read_missing");
  const parts = [response.content]; let count = 0;
  while (!response.eof) {
    response = f.call("read_file", { request_id: `page-${++count}`, path: f.allowed, offset: response.next_offset, expected_sha256: response.sha256 });
    expect(response.ok).toBe(true); parts.push(response.content);
  }
  expect(parts.join("")).toBe(value); expect(f.files.verify(f.proof, [f.allowed]).read_files).toEqual([f.allowed]);
});
test("traversal, symlinks, git metadata and non-unique edits cannot mutate the project", () => {
  const f = fixture(true, "same same\n");
  const read = f.call("read_file", { request_id: "read", path: "PROJECT.md" });
  expect(f.call("edit_file", { request_id: "ambiguous", path: "PROJECT.md", expected_sha256: read.sha256, old_text: "same", new_text: "new" })).toMatchObject({ ok: false, error: "workspace_tool_edit_ambiguous" });
  let n = 0;
  for (const path of ["../outside", "./PROJECT.md", ".git/config", "folder/../PROJECT.md", "/etc/passwd", "a//b"]) expect(f.call("read_file", { request_id: `bad-${n++}`, path }).ok).toBe(false);
  symlinkSync(f.allowed, join(f.stage!.fileScope().tree, "link"));
  expect(f.call("read_file", { request_id: "link", path: "link" }).ok).toBe(false);
  expect(readFileSync(f.allowed, "utf8")).toBe("same same\n");
});
test("a lost write receipt stays unknown until retained staged bytes are reconciled without another write", () => {
  const f = fixture(), staged = join(f.stage!.fileScope().tree, "new.txt"), input = { request_id: "write", path: "new.txt", expected_sha256: null, content: "after" };
  let fail = true;
  f.setCheck(() => { if (fail) { try { if (readFileSync(staged, "utf8") === "after") throw new Error("owner interrupted after staged write"); } catch (e) { if ((e as NodeJS.ErrnoException).code !== "ENOENT") throw e; } } });
  expect(() => f.call("write_file", input)).toThrow("owner interrupted"); fail = false;
  const before = statSync(staged).mtimeMs, reopened = new NativeWorkspaceFiles(f.config, f.authority, () => {});
  expect(() => reopened.call("controlmesh_write_file", input)).toThrow("workspace_tool_outcome_unknown");
  const recovered = reopened.reconcile("write"); expect(recovered).toMatchObject({ ok: true, staged: true });
  expect(statSync(staged).mtimeMs).toBe(before); expect(reopened.call("controlmesh_write_file", input)).toEqual(recovered);
  expect(() => reopened.verify([], [])).toThrow("workspace_tool_call_unobserved");
  expect(reopened.verify([{ tool: "controlmesh_write_file", input, output: canonical(recovered) }], []).written_files).toEqual([join(f.workspace, "new.txt")]);
});
test("source edits, canceled ownership, fake native output and changed staged results reject", () => {
  const f = fixture(); f.call("write_file", { request_id: "new", path: "new.txt", expected_sha256: null, content: "after" });
  expect(() => f.files.verify([{ ...f.proof[0], output: "invented" }], [])).toThrow("workspace_tool_call_unproven");
  writeFileSync(join(f.stage!.fileScope().tree, "new.txt"), "unrecorded");
  expect(() => f.files.verify(f.proof, [])).toThrow("workspace_tool_write_changed");
  f.kernel.cancel(actor, "cancel", "task", f.kernel.inspect(actor, "task").revision);
  expect(() => f.call("read_file", { request_id: "cancelled", path: "PROJECT.md" })).toThrow("task_not_executable");
  const g = fixture(false); writeFileSync(g.allowed, "changed source");
  expect(() => g.call("read_file", { request_id: "changed", path: "PROJECT.md" })).toThrow("workspace_tool_source_changed");
});
test("a real Node MCP workspace client exposes only file tools and enforces the registered scope", async () => {
  const f = fixture(false), config = prepareNativeAgentConfiguration(join(f.root, "ipc"), Bun.which("node")!, "task", [], null, "workspace.v1");
  const broker = new NativeAgentChannel(f.lease, config, () => {}, { assertDispatched: () => f.kernel.withLease(actor, f.lease, () => {}), call: async (tool, input) => f.files.call(tool, input) });
  cleanup.push(() => broker.close()); await broker.start();
  const client = new NativeMcpTestClient(broker.command); cleanup.push(() => client.close()); await client.initialize();
  const listed = (await client.request("tools/list")).result?.tools;
  expect(listed?.map(tool => tool.name)).toEqual(["read_file", "write_file", "edit_file"]);
  expect(listed?.find(tool => tool.name === "read_file")).toMatchObject({ inputSchema: {
    required: ["request_id", "path"], properties: { expected_sha256: { type: "string", pattern: "^[a-f0-9]{64}$" } },
  } });
  expect(listed?.find(tool => tool.name === "write_file")).toMatchObject({ inputSchema: {
    required: ["request_id", "path", "expected_sha256", "content"],
    properties: { expected_sha256: { type: "string", pattern: "^(?:[a-f0-9]{64}|missing)$" } },
  } });
  const mistakenRead = { request_id: "first-read", path: "PROJECT.md", expected_sha256: "missing" };
  const mistaken = await client.tool("read_file", mistakenRead);
  const failure = JSON.parse(mistaken.result!.content![0].text);
  expect(failure).toMatchObject({ ok: false, error: "workspace_tool_content_changed" });
  expect(failure.hint).toContain("omit expected_sha256");
  expect(JSON.parse((await client.tool("read_file", mistakenRead)).result!.content![0].text)).toEqual(failure);
  expect(() => f.files.verify([], [f.allowed])).toThrow();
  const allowed = await client.tool("read_file", { request_id: "allowed", path: "PROJECT.md" });
  expect(JSON.parse(allowed.result!.content![0].text)).toMatchObject({ ok: true, content: "original current fact\n" });
  const denied = await client.tool("read_file", { request_id: "denied", path: "ungranted.txt" });
  expect(JSON.parse(denied.result!.content![0].text)).toMatchObject({ ok: false, error: "workspace_tool_path_not_granted" });
  expect((await client.tool("send", { request_id: "send", recipient_task: "other", text: "no" })).error).toBeDefined();
  await broker.close(); expect(readdirSync(config.directory)).toEqual(["client.mjs"]);
});
test("the persisted request budget survives reopen and identical retries do not spend another slot", () => {
  const f = fixture(false);
  for (let n = 0; n < 256; n++) expect(f.call("read_file", { request_id: `read-${n}`, path: "PROJECT.md" }).ok).toBe(true);
  const reopened = new NativeWorkspaceFiles(f.config, f.authority, () => {});
  expect(reopened.call("controlmesh_read_file", { request_id: "read-0", path: "PROJECT.md" }).ok).toBe(true);
  expect(() => reopened.call("controlmesh_read_file", { request_id: "overflow", path: "PROJECT.md" })).toThrow("workspace_tool_budget_exhausted");
});
test("finished receipts tolerate only associated interrupted metadata writes; unknown files are preserved and rejected", () => {
  const f = fixture(false); f.call("read_file", { request_id: "read", path: "PROJECT.md" });
  const name = readdirSync(f.journal).find(name => /^[a-f0-9]{64}\.json$/.test(name))!;
  const pending = join(f.journal, name.slice(0, -5) + ".aaaaaaaa-0000-0000-0000-000000000001.pending");
  writeFileSync(pending, "incomplete private metadata write", { mode: 0o600 });
  expect(f.files.verify(f.proof, [f.allowed]).read_files).toEqual([f.allowed]);
  const foreign = join(f.journal, "foreign.txt"); writeFileSync(foreign, "preserved");
  expect(() => f.files.verify(f.proof, [f.allowed])).toThrow("workspace_tool_receipts_unresolved");
  expect(readFileSync(foreign, "utf8")).toBe("preserved");
});
