import { writeFileSync } from "node:fs";
const [mode, destination] = Bun.argv.slice(2);
if (mode === "success") {
  console.log("synthetic provider result");
} else if (mode === "flood") {
  console.log("x".repeat(100_000));
} else if (mode === "quota") {
  console.error("synthetic provider quota error");
  setInterval(() => {}, 1000);
} else if (mode === "hold") {
  process.on("SIGTERM", () => {});
  if (destination) writeFileSync(destination, JSON.stringify({ root: process.pid }));
  setInterval(() => {}, 1000);
} else if (mode === "family" || mode === "orphan") {
  process.on("SIGTERM", () => {});
  const child = Bun.spawn([process.execPath, import.meta.path, "hold"], { stdin: "ignore", stdout: "inherit", stderr: "inherit" });
  writeFileSync(destination, JSON.stringify({ root: process.pid, grandchild: child.pid }));
  if (mode === "orphan") process.exit(0);
  setInterval(() => {}, 1000);
}
