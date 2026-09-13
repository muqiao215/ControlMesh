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
    db.sql.exec("DROP TABLE backstage_events; PRAGMA user_version=29;"); db.close(); db = new RuntimeDatabase(path);
    expect(db.sql.query("PRAGMA user_version").get()).toEqual({ user_version: 30 });
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
