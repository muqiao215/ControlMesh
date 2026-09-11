import { afterEach, expect, test } from "bun:test";
import { FeishuTenantCredentials, type DeliveryContext } from "../src";
import { digest, RuntimeConflict } from "../src/value";

const cleanup: (() => void | Promise<void>)[] = [];
afterEach(async () => { for (const close of cleanup.splice(0).reverse()) await close(); });
const context = (controller = new AbortController()): DeliveryContext => ({ signal: controller.signal, assertCurrent() {} });
async function until(check: () => boolean) {
  const deadline = performance.now() + 2000;
  while (!check()) { if (performance.now() >= deadline) throw new Error("fixture_timeout"); await Bun.sleep(5); }
}
function fixture(timeout = 500) {
  let calls = 0, now = 0, secret = "fixture_secret_a", allowed = true;
  let response: (call: number) => Response | Promise<Response> = call => Response.json({ code: 0, tenant_access_token: `fixture_token_${call}`, expire: 7200 });
  const bodies: any[] = [], held: (() => void)[] = [];
  const server = Bun.serve({ hostname: "127.0.0.1", port: 0, async fetch(request) {
    expect(new URL(request.url).pathname).toBe("/open-apis/auth/v3/tenant_access_token/internal");
    expect(request.method).toBe("POST"); expect(request.headers.has("authorization")).toBe(false);
    const body = await request.json(); bodies.push(body);
    expect(body.app_id).toBe("cli_fixture"); calls++; return response(calls);
  } });
  cleanup.push(() => { held.splice(0).forEach(release => release()); server.stop(true); });
  const request = (async (input: string | URL | Request, init?: RequestInit) => {
    const url = new URL(String(input)); expect(url.origin).toBe("https://open.feishu.cn"); expect(init?.redirect).toBe("error");
    return fetch(`${server.url.origin}${url.pathname}`, init);
  }) as typeof fetch;
  const config = { app_id: "cli_fixture", assertCurrent() { if (!allowed) throw new RuntimeConflict("configuration_revoked"); },
    load() { return { app_id: "cli_fixture", app_secret: secret, revision: digest(secret) }; } };
  const owner = new FeishuTenantCredentials(config, request, () => now, timeout); cleanup.push(() => owner.stop());
  return { owner, config, request, bodies, calls: () => calls, advance(ms: number) { now += ms; },
    rotate() { secret = "fixture_secret_b"; }, revoke() { allowed = false; },
    respond(fn: typeof response) { response = fn; },
    hold() { let release!: () => void; const wait = new Promise<void>(resolve => { release = resolve; }); held.push(release); return { wait, release }; },
  };
}

test("one selected app refresh serves concurrent callers and reuses an unexpired token", async () => {
  const f = fixture(), hold = f.hold();
  f.respond(async () => { await hold.wait; return Response.json({ code: 0, tenant_access_token: "fixture_token", expire: 7200 }); });
  const pending = Array.from({ length: 20 }, () => f.owner.get(context()));
  await until(() => f.calls() === 1); hold.release();
  expect(await Promise.all(pending)).toEqual(Array(20).fill("fixture_token"));
  expect(await f.owner.get(context())).toBe("fixture_token"); expect(f.calls()).toBe(1);
});

test("a short token lifetime is not inflated to the Python owner's sixty-second floor", async () => {
  const f = fixture(); f.respond(call => Response.json({ code: 0, tenant_access_token: `fixture_${call}`, expire: 1 }));
  expect(await f.owner.get(context())).toBe("fixture_1"); f.advance(850);
  expect(await f.owner.get(context())).toBe("fixture_1"); f.advance(100);
  expect(await f.owner.get(context())).toBe("fixture_2"); expect(f.calls()).toBe(2);
});

test("canceling one delivery does not abort the shared refresh needed by another", async () => {
  const f = fixture(), hold = f.hold(), controller = new AbortController();
  f.respond(async () => { await hold.wait; return Response.json({ code: 0, tenant_access_token: "fixture_token", expire: 7200 }); });
  const cancelled = f.owner.get(context(controller)).catch(error => error), other = f.owner.get(context());
  await until(() => f.calls() === 1); controller.abort();
  expect((await cancelled).code).toBe("feishu_auth_interrupted"); hold.release();
  expect(await other).toBe("fixture_token"); expect(f.calls()).toBe(1);
});

test("shutdown interrupts a held refresh and prevents another request", async () => {
  const f = fixture(), hold = f.hold(); f.respond(async () => { await hold.wait; return Response.json({ code: 0 }); });
  const pending = f.owner.get(context()).catch(error => error);
  await until(() => f.calls() === 1); await f.owner.stop();
  expect((await pending).code).toBe("feishu_auth_interrupted");
  await expect(f.owner.get(context())).rejects.toThrow("feishu_credentials_stopping"); expect(f.calls()).toBe(1);
});

test("credential rotation invalidates the cached token without selecting another app", async () => {
  const f = fixture(); expect(await f.owner.get(context())).toBe("fixture_token_1");
  f.rotate(); expect(await f.owner.get(context())).toBe("fixture_token_2");
  expect(f.bodies).toEqual([{ app_id: "cli_fixture", app_secret: "fixture_secret_a" }, { app_id: "cli_fixture", app_secret: "fixture_secret_b" }]);
  f.revoke(); await expect(f.owner.get(context())).rejects.toThrow("configuration_revoked"); expect(f.calls()).toBe(2);
});

test("a prepared delivery cannot use an expired or rotated credential token", async () => {
  const f = fixture();
  const token = await f.owner.get(context()); f.owner.assertToken(token);
  f.advance(7_200_001); expect(() => f.owner.assertToken(token)).toThrow("feishu_token_unavailable");
  const fresh = await f.owner.get(context()); f.rotate(); expect(() => f.owner.assertToken(fresh)).toThrow("feishu_token_unavailable");
  expect(f.calls()).toBe(2);
});

test("a response from an obsolete in-flight credential cannot populate the new cache", async () => {
  const f = fixture(), hold = f.hold();
  f.respond(async call => { if (call === 1) await hold.wait; return Response.json({ code: 0, tenant_access_token: `fixture_token_${call}`, expire: 7200 }); });
  const old = f.owner.get(context()).catch(error => error); await until(() => f.calls() === 1); f.rotate();
  expect(await f.owner.get(context())).toBe("fixture_token_2"); hold.release();
  expect(await old).toBeInstanceOf(RuntimeConflict); expect(await f.owner.get(context())).toBe("fixture_token_2"); expect(f.calls()).toBe(2);
});

test("an authentication rejection is latched until explicit retry or credential rotation", async () => {
  const f = fixture(); f.respond(() => Response.json({ code: 10003, msg: "fixture_secret_a must never enter an error" }));
  const failure = await f.owner.get(context()).catch(error => error);
  expect(failure.message).toBe("feishu_auth_rejected"); f.advance(1_000_000);
  await expect(f.owner.get(context())).rejects.toThrow("feishu_auth_rejected"); expect(f.calls()).toBe(1);
  f.respond(() => Response.json({ code: 0, tenant_access_token: "fixture_recovered", expire: 7200 })); f.owner.retry();
  expect(await f.owner.get(context())).toBe("fixture_recovered"); expect(f.calls()).toBe(2);
});

test("HTTP service failure backs off without returning provider bodies or making repeated requests", async () => {
  const f = fixture(); f.respond(() => new Response("fixture_secret_a", { status: 503 }));
  await expect(f.owner.get(context())).rejects.toThrow("feishu_auth_unavailable");
  await expect(f.owner.get(context())).rejects.toThrow("feishu_auth_unavailable"); expect(f.calls()).toBe(1);
  f.advance(30_001); f.respond(() => Response.json({ code: 0, tenant_access_token: "fixture_recovered", expire: 7200 }));
  expect(await f.owner.get(context())).toBe("fixture_recovered"); expect(f.calls()).toBe(2);
});

test("auth timeout drains HTTP and applies backoff to subsequent delivery preparations", async () => {
  const f = fixture(100), hold = f.hold(); f.respond(async () => { await hold.wait; return Response.json({ code: 0 }); });
  await expect(f.owner.get(context())).rejects.toThrow("feishu_auth_timeout");
  await expect(f.owner.get(context())).rejects.toThrow("feishu_auth_timeout"); expect(f.calls()).toBe(1);
});

for (const expire of [0, -1, "7200", 1.5, 86401]) test(`invalid tenant expiry ${JSON.stringify(expire)} is rejected`, async () => {
  const f = fixture(); f.respond(() => Response.json({ code: 0, tenant_access_token: "fixture_token", expire }));
  await expect(f.owner.get(context())).rejects.toThrow("feishu_auth_response_invalid");
});

test("oversized, redirected and malformed auth responses fail without leaking their contents", async () => {
  const f = fixture(); f.respond(() => new Response("fixture_secret_a".repeat(2000)));
  await expect(f.owner.get(context())).rejects.toThrow("feishu_auth_response_invalid");
  f.owner.retry(); f.respond(() => Response.redirect("https://example.invalid/credential-leak"));
  await expect(f.owner.get(context())).rejects.toThrow("feishu_auth_unavailable");
  f.owner.retry(); f.respond(() => new Response("fixture_secret_a is not JSON"));
  await expect(f.owner.get(context())).rejects.toThrow("feishu_auth_unavailable"); expect(f.calls()).toBe(3);
});
