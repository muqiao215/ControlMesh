import { expect, test } from "bun:test";
import { join } from "node:path";
import { decodeHostJob, hostJobStates, hostStepStates, mergeHostJob } from "../src/host-job-model";

const job = (state: string, stepState: string) => ({ job_id: "job", state, created_at: "2026-09-13T00:00:00Z", updated_at: "2026-09-13T01:00:00Z", steps: [{ id: "test", command: "echo fixture", state: stepState }] });
test("host job terminal merging agrees with live Python across task and step state pairs", async () => {
  const pairs = [...hostJobStates.flatMap(a => hostJobStates.map(b => [job(a, "pending"), job(b, "pending")])),
    ...hostStepStates.flatMap(a => hostStepStates.map(b => [job("running", a), job("running", b)]))];
  const child = Bun.spawn(["uv", "run", "python", "-c", "import json,sys; from controlmesh.runtime.host_jobs import HostJob,_merge_job; print(json.dumps([_merge_job(HostJob.from_dict(a),HostJob.from_dict(b)).to_dict() for a,b in json.load(sys.stdin)]))"],
    { cwd: join(import.meta.dir, "../../.."), stdin: new Response(JSON.stringify(pairs)), stdout: "pipe", stderr: "pipe" });
  const output = await new Response(child.stdout).text(); expect(await child.exited).toBe(0);
  expect(pairs.map(([a,b]) => mergeHostJob(a,b))).toEqual(JSON.parse(output));
});
test("host job updates cannot replace approved commands or remove terminal steps", () => {
  const prior = decodeHostJob(job("completed", "completed"));
  expect(() => mergeHostJob(prior, { ...prior, steps: [] })).toThrow("host_job_terminal_step_removed");
  const changed = { ...prior.steps[0]!, command: "different", command_digest: "" };
  expect(() => mergeHostJob(prior, { ...prior, steps: [changed] })).toThrow("host_job_step_definition_changed");
  expect(() => decodeHostJob({ ...prior, steps: [{ ...prior.steps[0]!, command_digest: "bad" }] })).toThrow("host_job_command_digest_mismatch");
  expect(() => decodeHostJob({ ...prior, steps: [prior.steps[0], prior.steps[0]] })).toThrow("duplicate_host_job_step");
  expect(() => mergeHostJob(prior, { ...prior, job_id: "other" })).toThrow("host_job_identity_changed");
  expect(prior.steps[0]!.command).toBe("echo fixture");
});
