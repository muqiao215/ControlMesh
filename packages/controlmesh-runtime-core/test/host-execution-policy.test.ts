import { expect, test } from "bun:test";
import { resolve } from "node:path";
import { classifyHostExecution } from "../src/host-execution-policy";

test("host route decisions match the current Python classifier on explicit and heuristic commands", async () => {
  const cases = ["test_execution", "long_shell", "release_validation", "uv_build", "git_write", "repo_write", "repo_publish", "github_release", "publish", "release_publish", "unknown", "", " test_execution "]
    .flatMap(workunit_kind => ["", "echo plain", "PYTEST -q", "uv build", "git push", "gh release create v1", "twine upload dist/*", "uv publish"].map(command => ({ workunit_kind, command })));
  const child = Bun.spawn(["uv", "run", "python", "-c", "import sys,json; from dataclasses import asdict; from types import SimpleNamespace; from controlmesh.tasks.host_execution import classify_host_execution; print(json.dumps([asdict(classify_host_execution(SimpleNamespace(**x))) for x in json.load(sys.stdin)]))"],
    { cwd: resolve(import.meta.dir, "../../.."), env: { ...process.env, UV_CACHE_DIR: "/tmp/cm-runtime-uv-cache" }, stdin: "pipe", stdout: "pipe", stderr: "pipe" });
  child.stdin.write(JSON.stringify(cases)); child.stdin.end();
  const [code, output, errors] = await Promise.all([child.exited, new Response(child.stdout).text(), new Response(child.stderr).text()]);
  expect({ code, errors: code ? errors : "" }).toEqual({ code: 0, errors: "" });
  const expected = JSON.parse(output);
  cases.forEach((entry, index) => expect(classifyHostExecution(entry)).toEqual(expected[index]));
  expect(classifyHostExecution({ command: "echo safe" }).route_to_host).toBe(false);
  expect(() => classifyHostExecution({ command: {} })).toThrow("invalid_host_routing_fields");
}, 20000);
