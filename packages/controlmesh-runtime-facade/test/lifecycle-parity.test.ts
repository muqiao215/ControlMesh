import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import {
  diffLifecycleParity,
  parseLifecycleMatrix,
  runLifecycleCandidate,
} from "../src/lifecycle-parity";
import { runDualLifecycleParity } from "../scripts/check-lifecycle-parity";

const root = resolve(import.meta.dir, "../../..");
const matrix = parseLifecycleMatrix(
  JSON.parse(readFileSync(resolve(root, "tests/golden/fixtures/tasks/lifecycle.matrix.json"), "utf8")),
);

describe("internal lifecycle candidate", () => {
  test("independently matches every Python lifecycle case", () => {
    const observations = runLifecycleCandidate(matrix);
    const report = diffLifecycleParity(matrix, observations);
    expect(report.status).toBe("pass");
    expect(report.case_count).toBe(14);
    expect(report.matched_case_count).toBe(14);
    expect(new Set(report.required_domains)).toEqual(new Set(matrix.required_domains));
  });

  test("structured diff fails closed on value drift", () => {
    const observations = runLifecycleCandidate(matrix);
    observations[0]!.actual = { ...observations[0]!.actual, event_types: ["wrong.event"] };
    const report = diffLifecycleParity(matrix, observations);
    expect(report.status).toBe("fail");
    expect(report.diffs).toEqual([
      {
        case_id: "create.basic",
        path: "/event_types/0",
        expected: "task.folder.seeded",
        actual: "wrong.event",
      },
    ]);
  });

  test("structured diff fails closed on missing and extra cases", () => {
    const observations = runLifecycleCandidate(matrix);
    const missing = observations.slice(1);
    missing.push({ ...observations[1]!, id: "extra.case" });
    const report = diffLifecycleParity(matrix, missing);
    expect(report.status).toBe("fail");
    expect(report.missing_case_ids).toEqual(["create.basic"]);
    expect(report.extra_case_ids).toEqual(["extra.case"]);
  });

  test("dual-run gate retains Python ownership and keeps mutation private", () => {
    const { report, gate } = runDualLifecycleParity();
    expect(report.status).toBe("pass");
    expect(gate.candidate_admitted).toBe(true);
    expect(gate.production_owner).toBe("python");
    expect(gate.rollback_owner).toBe("python");
    expect(gate.public_mutation_api).toBe(false);
  });
});
