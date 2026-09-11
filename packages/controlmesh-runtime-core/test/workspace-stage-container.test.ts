import { afterEach, expect, test } from "bun:test";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { WorkspaceStage } from "../src/workspace-stage";
import { ContainerProcessSupervisor } from "../src/containers/process";
import { planContainer, type ContainerConfiguration } from "../src/containers/plan";
import { digest } from "../src/value";

const roots: string[] = [], image = process.env.CM_CONTAINER_TEST_IMAGE;
const actual = image ? test : test.skip;
afterEach(() => { for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true }); });
function fixture(all = false) {
  const root = realpathSync(mkdtempSync(join(tmpdir(), "cm-stage-container-"))); roots.push(root);
  const workspace = join(root, "project"), state = join(root, "state"), control = join(root, "containers");
  for (const path of [workspace, state, control]) mkdirSync(path, { mode: 0o700 });
  mkdirSync(join(workspace, "src")); mkdirSync(join(workspace, ".git"));
  writeFileSync(join(workspace, "PROJECT.md"), "canonical context\n"); writeFileSync(join(workspace, "src/a.ts"), "canonical source\n");
  writeFileSync(join(workspace, ".git/config"), "protected git\n");
  if (!all) symlinkSync("../PROJECT.md", join(workspace, "src/context-link"));
  const stage = WorkspaceStage.create(state, workspace, [all ? workspace : join(workspace, "src")], digest("issued native write"), run => run());
  const config: ContainerConfiguration = { docker: "/usr/bin/docker", socket: "/run/docker.sock", state_root: control,
    image_id: image ?? `sha256:${"a".repeat(64)}`, node_executable: "/usr/local/bin/node", workspace_layout: "native", memory_mb: 256 };
  return { root, workspace, state, control, stage, config };
}

test("projected execution cannot also mount canonical writable roots, remap credentials or overlap writable targets", () => {
  const f = fixture(), projection = f.stage.projection();
  expect(() => planContainer(f.config, f.workspace, [join(f.workspace, "src")], false, projection)).toThrow("container_projection_requires_readonly_canonical_workspace");
  expect(() => planContainer(f.config, f.workspace, [], false, [{ source: f.workspace, target: f.workspace, readonly: false }])).toThrow("container_projection_canonical_write_forbidden");
  expect(() => planContainer(f.config, f.workspace, [], false, [{ source: f.state, target: join(f.workspace, "credentials"), readonly: true }])).toThrow("container_projection_readonly_scope_invalid");
  expect(() => planContainer(f.config, f.workspace, [], false, [...projection, { source: f.state, target: join(f.workspace, "src/nested"), readonly: false }])).toThrow("container_projection_overlap");
  const plan = planContainer(f.config, f.workspace, [], false, projection);
  expect(plan.mounts.filter(mount => !mount.readonly).every(mount => mount.source.startsWith(f.stage.path))).toBe(true);
});

for (const all of [false, true]) actual(`real container writes only the staged ${all ? "whole project" : "source root"} at the original native path`, async () => {
  const f = fixture(all), projection = f.stage.projection();
  const code = `const fs=require('node:fs'); const denied={};
    fs.writeFileSync('src/a.ts','native staged result\\n'); fs.writeFileSync('src/new.ts','native new file\\n');
    for(const p of ${JSON.stringify(all ? [".git/config"] : ["PROJECT.md", "src/context-link", ".git/config"])}){
      try{fs.writeFileSync(p,'forbidden');denied[p]=false}catch{denied[p]=true}}
    console.log(JSON.stringify({cwd:process.cwd(),denied,inside:fs.existsSync('/.dockerenv')}));`;
  const result = await new ContainerProcessSupervisor(f.config).run({ command: [f.config.node_executable, "-e", code], cwd: f.workspace, env: {},
    timeout_ms: 20_000, execution_id: `stage-${all}`, writable_roots: [], no_network: true, workspace_projection: projection },
    { assertCurrent: () => f.stage.assertCurrent() });
  expect(result).toMatchObject({ reason: "exited", exit_code: 0, cleanup: "removed" });
  const observed = JSON.parse(result.stdout); expect(observed.cwd).toBe(f.workspace); expect(observed.inside).toBe(true);
  expect(Object.values(observed.denied).every(value => value === true)).toBe(true);
  expect(readFileSync(join(f.workspace, "src/a.ts"), "utf8")).toBe("canonical source\n");
  expect(existsSync(join(f.workspace, "src/new.ts"))).toBe(false);
  expect(readFileSync(join(f.workspace, "PROJECT.md"), "utf8")).toBe("canonical context\n");
  expect(readFileSync(join(f.workspace, ".git/config"), "utf8")).toBe("protected git\n");
  const proposal = f.stage.seal(run => run()); f.stage.promote(run => run(), proposal.proposal_digest);
  expect(readFileSync(join(f.workspace, "src/a.ts"), "utf8")).toBe("native staged result\n");
  expect(readFileSync(join(f.workspace, "src/new.ts"), "utf8")).toBe("native new file\n");
}, 30_000);
