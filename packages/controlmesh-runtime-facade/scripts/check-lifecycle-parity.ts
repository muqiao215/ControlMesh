#!/usr/bin/env bun
import { resolve } from "node:path";
import { readFileSync } from "node:fs";
import {
  diffLifecycleParity,
  parseLifecycleMatrix,
  runLifecycleCandidate,
  type LifecycleParityReport,
} from "../src/lifecycle-parity";

const root = resolve(import.meta.dir, "../../..");
const fixturePath = resolve(root, "tests/golden/fixtures/tasks/lifecycle.matrix.json");
const gatePath = resolve(root, "tests/golden/fixtures/tasks/lifecycle.rollback-gate.json");

export interface LifecycleRollbackGate {
  schema_version: "controlmesh.lifecycle_rollback_gate.v1";
  matrix_schema_version: "controlmesh.task_lifecycle_golden.v2";
  matrix_sha256: string;
  candidate: "typescript-internal-runtime-facade";
  candidate_admitted: boolean;
  production_owner: "python";
  rollback_owner: "python";
  public_mutation_api: false;
  covered_domains: string[];
  case_count: number;
  matched_case_count: number;
  diff_count: number;
  missing_case_count: number;
  extra_case_count: number;
}

function pythonOracle(): string {
  const process = Bun.spawnSync(
    ["uv", "run", "python", "scripts/generate_task_lifecycle_goldens.py", "--stdout"],
    { cwd: root, stdout: "pipe", stderr: "pipe" },
  );
  if (process.exitCode !== 0) {
    throw new Error(`Python lifecycle oracle failed: ${process.stderr.toString().trim()}`);
  }
  return process.stdout.toString();
}

function gateFor(report: LifecycleParityReport, matrixText: string): LifecycleRollbackGate {
  const digest = new Bun.CryptoHasher("sha256").update(matrixText).digest("hex");
  return {
    schema_version: "controlmesh.lifecycle_rollback_gate.v1",
    matrix_schema_version: report.matrix_schema_version,
    matrix_sha256: digest,
    candidate: "typescript-internal-runtime-facade",
    candidate_admitted: report.status === "pass",
    production_owner: "python",
    rollback_owner: "python",
    public_mutation_api: false,
    covered_domains: report.required_domains,
    case_count: report.case_count,
    matched_case_count: report.matched_case_count,
    diff_count: report.diffs.length,
    missing_case_count: report.missing_case_ids.length,
    extra_case_count: report.extra_case_ids.length,
  };
}

export function runDualLifecycleParity(): {
  report: LifecycleParityReport;
  gate: LifecycleRollbackGate;
} {
  const generatedText = pythonOracle();
  const committedText = readFileSync(fixturePath, "utf8");
  if (generatedText !== committedText) {
    throw new Error("Committed lifecycle matrix drifted from the Python oracle");
  }
  const matrix = parseLifecycleMatrix(JSON.parse(generatedText));
  const observations = runLifecycleCandidate(matrix);
  const report = diffLifecycleParity(matrix, observations);
  return { report, gate: gateFor(report, generatedText) };
}

function render(value: unknown): string {
  return `${JSON.stringify(value, null, 2)}\n`;
}

if (import.meta.main) {
  const write = process.argv.includes("--write");
  const { report, gate } = runDualLifecycleParity();
  if (report.status !== "pass") {
    console.error(render(report));
    process.exit(1);
  }
  const renderedGate = render(gate);
  if (write) {
    await Bun.write(gatePath, renderedGate);
    console.log(`wrote ${gatePath.slice(root.length + 1)}`);
  } else {
    const committed = await Bun.file(gatePath).text();
    if (committed !== renderedGate) {
      console.error("Lifecycle rollback gate drifted; run with --write");
      process.exit(1);
    }
    console.log(
      `lifecycle parity passed: ${report.matched_case_count}/${report.case_count} cases, Python retained as rollback owner`,
    );
  }
}
