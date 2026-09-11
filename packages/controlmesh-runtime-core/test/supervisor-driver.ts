import { ProcessSupervisor } from "../src/process-supervisor";
import { join } from "node:path";
import { elapsedMs } from "../src/elapsed-clock";
const leaseDeadline = elapsedMs() + 600;
await new ProcessSupervisor().run({ command: [process.execPath, join(import.meta.dir, "provider-child.ts"), "family", Bun.argv[2]], cwd: import.meta.dir, env: {}, timeout_ms: 10_000 }, {
  assertCurrent() {}, ...(Bun.argv[3] === "bounded-lease" ? { remainingMs: () => leaseDeadline - elapsedMs() } : {}),
});
