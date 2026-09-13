import { expect, test } from "bun:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { RuntimeDatabase } from "../src/database";
import { RuntimeEventStore } from "../src/runtime-events";
import { parseRuntimeSessionKey, runtimeSessionStorageKey } from "../src/runtime-session-key";

test("session keys preserve large numeric identity, typed strings and legacy aliases", async () => {
  const cases = ["123", "-123:9", "tg:00123", "terminal:18446744073709551615", "v2:feishu:s:oc_%E4%B8%AD%3A%2F:s:thread%21", "v2:api:s:123", "v2:api:i:123", "v2:api:s::i:9"];
  const child = Bun.spawn(["uv", "run", "python", "-c", "import json,sys; from controlmesh.session.key import SessionKey; print(json.dumps([SessionKey.parse(k).storage_key for k in json.load(sys.stdin)]))"], { cwd: join(import.meta.dir, "../../.."), stdin: new Response(JSON.stringify(cases)), stdout: "pipe", stderr: "pipe" });
  const output = await new Response(child.stdout).text(); expect(await child.exited).toBe(0);
  expect(cases.map(runtimeSessionStorageKey)).toEqual(JSON.parse(output));
  expect(parseRuntimeSessionKey(cases[3]!).chat.value).toBe("18446744073709551615");
  expect(runtimeSessionStorageKey("v2:api:s:123")).not.toBe(runtimeSessionStorageKey("api:123"));
  for (const invalid of ["v2:api:s:%FF", "api:1:2:3", "../bad:1", "tg:NaN"]) expect(() => runtimeSessionStorageKey(invalid)).toThrow();
});

test("backstage event migration, reopen, principal isolation and retry identity", () => {
  const root = mkdtempSync(join(tmpdir(), "cm-events-")), path = join(root, "runtime.sqlite");
  let db = new RuntimeDatabase(path);
  try {
    // A prior schema has no backstage table. Upgrade must retain unrelated state.
    db.sql.exec("DROP TABLE process_output_chunks; DROP TABLE host_jobs; DROP TABLE backstage_events; PRAGMA user_version=29;"); db.close(); db = new RuntimeDatabase(path);
    expect(db.sql.query("PRAGMA user_version").get()).toEqual({ user_version: 32 });
    const store = new RuntimeEventStore(db);
    const event = { event_id: "one", session_key: "123", event_type: "progress", payload: { state: "running" }, created_at: "2026-09-13T00:00:00Z", transport: "tg", chat_id: 123, topic_id: null };
    store.append("owner", event); store.append("owner", event);
    expect(() => store.append("owner", { ...event, payload: { changed: true } })).toThrow("runtime_event_id_conflict");
    store.append("other", { ...event, payload: { private: true } });
    store.append("owner", { ...event, event_id: "two", session_key: "tg:123" });
    expect(store.readRecent("owner", "tg:123", 1).map(x => x.event_id)).toEqual(["two"]);
    expect(store.readRecent("owner", "123", 0).map(x => x.event_id)).toEqual(["one", "two"]);
    expect(store.readRecent("unrelated", "123")).toEqual([]);
    expect(() => store.append("owner", { ...event, event_id: "unsafe", chat_id: 18446744073709551615 })).toThrow("invalid_runtime_event");
    db.close(); db = new RuntimeDatabase(path);
    expect(new RuntimeEventStore(db).readRecent("owner", "tg:123")).toHaveLength(2);
    expect(db.sql.query("SELECT COUNT(*) AS n FROM events").get()).toEqual({ n: 0 });
  } finally { db.close(); rmSync(root, { recursive: true, force: true }); }
});

test("legacy JSONL import preserves Python integers and rolls back a conflicting batch", async () => {
  const db = new RuntimeDatabase(":memory:"), store = new RuntimeEventStore(db);
  try {
    const text = '{"event_id":"large","session_key":"terminal:18446744073709551615","event_type":"progress","payload":{"negative":-18446744073709551615,"nested":[18446744073709551615]},"created_at":"2026-09-13","transport":"terminal","chat_id":18446744073709551615,"topic_id":null}\n';
    const key = "terminal:18446744073709551615";
    expect(store.importJsonl("owner", key, text)).toEqual({ imported: 1, replayed: 0 });
    expect(store.importJsonl("owner", key, text)).toEqual({ imported: 0, replayed: 1 });
    expect(store.readRecent("owner", key)[0]!.chat_id).toBe(18446744073709551615n);
    const exported = store.exportJsonl("owner", key);
    const child = Bun.spawn(["uv", "run", "python", "-c", "import json,sys; a,b=json.load(sys.stdin); assert json.loads(a)==json.loads(b); print('exact')"], { cwd: join(import.meta.dir, "../../.."), stdin: new Response(JSON.stringify([text, exported])), stdout: "pipe", stderr: "pipe" });
    expect(await new Response(child.stdout).text()).toBe("exact\n"); expect(await child.exited).toBe(0);
    const newEvent = text.replace('"large"', '"new"');
    expect(() => store.importJsonl("owner", key, newEvent + text.replace('"progress"', '"changed"'))).toThrow("runtime_event_id_conflict");
    expect(store.readRecent("owner", key)).toHaveLength(1);
    expect(() => store.importJsonl("owner", key, newEvent + "broken\n")).toThrow();
    expect(() => store.importJsonl("owner", "tg:1", newEvent)).toThrow("runtime_event_import_session_mismatch");
    expect(store.readRecent("owner", key)).toHaveLength(1);
    expect(store.exportJsonl("other", key)).toBe("");
  } finally { db.close(); }
});

test("event codec refuses unproven rounded numbers and excessive nesting", async () => {
  const { parseRuntimeEventJson, runtimeEventJson } = await import("../src/runtime-event-json");
  expect(() => runtimeEventJson({ value: Number.MAX_SAFE_INTEGER + 1 })).toThrow("runtime_event_number_unproven");
  expect(() => parseRuntimeEventJson('{"value":1e30}')).toThrow("runtime_event_number_unproven");
  expect(() => runtimeEventJson({ value: undefined })).toThrow("invalid_runtime_event_json");
  let deep: unknown = null; for (let i = 0; i < 66; i++) deep = [deep];
  expect(() => runtimeEventJson(deep)).toThrow("runtime_event_depth_exceeded");
  expect(runtimeEventJson(parseRuntimeEventJson('{"value":9007199254740993}'))).toBe('{"value":9007199254740993}');
});

test("session history CLI preserves typed identifiers and has no principal override", async () => {
  const { parseRuntimeCli } = await import("../src/runtime-cli");
  expect(parseRuntimeCli(["session-events", "--socket", "/tmp/cm.sock", "--session", "v2:terminal:s:main%3Atopic", "--limit", "5", "--before", "50"])?.request)
    .toMatchObject({ op: "session_events", session_key: "v2:terminal:s:main%3Atopic", limit: 5, before: 50 });
  expect(() => parseRuntimeCli(["session-events", "--socket", "/tmp/cm.sock", "--session", "tg:1", "--principal", "other"])).toThrow("unknown_cli_option");
});

test("session pages bound response bytes and preserve older history when new events arrive", () => {
  const db = new RuntimeDatabase(":memory:"), store = new RuntimeEventStore(db);
  try {
    const event = { event_id: "", session_key: "tg:123", event_type: "progress", payload: { text: '"\\'.repeat(200000) }, created_at: "2026-09-13", transport: "tg", chat_id: 123, topic_id: null };
    for (let i = 1; i <= 4; i++) store.append("owner", { ...event, event_id: String(i) });
    store.append("foreign", { ...event, event_id: "private" });
    const first = store.readPage("owner", "123", 100);
    const ids = (page: { jsonl: string }) => page.jsonl.trim().split("\n").map(line => JSON.parse(line).event_id);
    expect(ids(first)).toEqual(["3", "4"]); expect(first.has_more).toBe(true);
    expect(Buffer.byteLength(first.jsonl)).toBeLessThanOrEqual(2 * 1024 * 1024);
    expect(Buffer.byteLength(JSON.stringify(first))).toBeLessThan(8 * 1024 * 1024);
    store.append("owner", { ...event, event_id: "new" });
    const second = store.readPage("owner", "tg:123", 100, first.next_before!);
    expect(ids(second)).toEqual(["1", "2"]); expect(second.has_more).toBe(false); expect(second.next_before).toBeNull();
    const single = store.readPage("owner", "123", 1); expect(ids(single)).toEqual(["new"]); expect(single.has_more).toBe(true);
    expect(store.readPage("empty", "123")).toMatchObject({ count: 0, jsonl: "", has_more: false, next_before: null });
    expect(() => store.readPage("owner", "123", 20, 0)).toThrow("invalid_runtime_event_cursor");
    expect(() => store.readPage("owner", "123", 101)).toThrow("invalid_local_event_limit");
  } finally { db.close(); }
});
