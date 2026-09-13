#!/usr/bin/env bun
import { importRuntimeEventFile } from "../src/runtime-event-import";
import { requireThat, RuntimeConflict } from "../src/value";

try {
  const args = process.argv.slice(2), values: Record<string, string> = {};
  let apply = false;
  for (let i = 0; i < args.length; i++) {
    const flag = args[i]!;
    if (flag === "--apply") { requireThat(!apply, "duplicate_migration_option"); apply = true; continue; }
    requireThat(["--source", "--database", "--principal", "--session", "--sha256"].includes(flag)
      && values[flag] === undefined && typeof args[i + 1] === "string" && !args[i + 1]!.startsWith("--"), "invalid_migration_option");
    values[flag] = args[++i]!;
  }
  for (const flag of ["--source", "--database", "--principal", "--session"]) requireThat(values[flag], "missing_migration_option");
  console.log(JSON.stringify(importRuntimeEventFile({ source: values["--source"]!, database: values["--database"]!, principal: values["--principal"]!, session: values["--session"]!, apply, sha256: values["--sha256"] })));
} catch (error) {
  console.error(JSON.stringify({ error: error instanceof RuntimeConflict ? error.code : "event_migration_failed" }));
  process.exitCode = 2;
}
