import { RuntimeDatabase, RuntimeKernel, type Principal } from "../src";

const [mode, database, barrier] = Bun.argv.slice(2);
const actor: Principal = { id: "operator", origin: "internal", device_id: `device-${process.pid}`, scopes: ["task:create", "task:execute", "task:admin"] };
const db = new RuntimeDatabase(database);
const kernel = new RuntimeKernel(db);
if (mode === "race") {
  await Bun.write(barrier, "ready");
  for await (const chunk of Bun.stdin.stream()) { if (chunk.byteLength) break; }
  try {
    const lease = kernel.claim(actor, `claim-${process.pid}`, "race", 1, 10_000);
    console.log(JSON.stringify({ won: true, fence: lease.fence }));
  } catch (error) {
    console.log(JSON.stringify({ won: false, error: (error as Error).message }));
  }
} else if (mode === "uncommitted") {
  db.sql.exec("BEGIN IMMEDIATE");
  db.sql.query("INSERT INTO tasks (task_id,principal,revision,status,raw) VALUES ('partial','operator',1,'waiting','{}')").run();
  await Bun.write(barrier, "uncommitted");
  for await (const _chunk of Bun.stdin.stream()) { /* hold the transaction until killed */ }
}
db.close();
