import { readFileSync } from "node:fs";
import { ContainerProcessSupervisor } from "../src";
const { config, spec } = JSON.parse(readFileSync(process.argv[2], "utf8"));
try { console.log(JSON.stringify(await new ContainerProcessSupervisor(config).run(spec, { assertCurrent() {} }))); }
catch (error) { console.error(String(error)); process.exitCode = 1; }
