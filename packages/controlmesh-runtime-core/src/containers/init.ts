import { readFileSync, mkdirSync } from "node:fs";
import { spawn } from "node:child_process";
import { containerLeaseCurrent } from "./lease";

// Compiled to CommonJS for the pinned image's Node runtime. PID 1 exiting also
// ends descendants that left their parent's process group inside this namespace.
const root = "/cm-control";
const uptime = () => Number(readFileSync("/proc/uptime", "utf8").split(" ")[0]) * 1000;
const boot = readFileSync("/proc/sys/kernel/random/boot_id", "utf8").trim();
function current(): void {
  const lease = JSON.parse(readFileSync(`${root}/lease.json`, "utf8"));
  if (!containerLeaseCurrent(lease, boot, uptime())) process.exit(124);
}
try {
  if (process.pid !== 1) process.exit(125);
  current();
  const configuration = JSON.parse(readFileSync(`${root}/launch.json`, "utf8"));
  const { command, environment } = configuration;
  if (!Array.isArray(command) || !command.length || command.some(item => typeof item !== "string" || item.includes("\0"))) process.exit(125);
  mkdirSync("/tmp/cm-home", { recursive: true, mode: 0o700 });
  const timer = setInterval(() => { try { current(); } catch { process.exit(124); } }, 50);
  process.on("SIGTERM", () => process.exit(143));
  process.on("SIGINT", () => process.exit(130));
  current();
  const child = spawn(command[0], command.slice(1), {
    cwd: "/workspace", env: { PATH: "/usr/local/bin:/usr/bin:/bin", HOME: "/tmp/cm-home", ...environment },
    stdio: ["pipe", "inherit", "inherit"],
  });
  child.stdin.on("error", () => {});
  process.stdin.pipe(child.stdin);
  child.on("error", () => process.exit(127));
  child.on("exit", (code, signal) => { clearInterval(timer); process.exit(code ?? (signal ? 128 : 127)); });
} catch { process.exit(125); }
