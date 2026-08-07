import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import "./build.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const dist = path.join(root, "dist");
const port = Number(process.env.PORT || 5173);

const types = new Map([
  [".html", "text/html; charset=utf-8"],
  [".js", "text/javascript; charset=utf-8"],
  [".css", "text/css; charset=utf-8"],
]);

Bun.serve({
  hostname: "127.0.0.1",
  port,
  async fetch(request) {
    const url = new URL(request.url);
    const pathname = url.pathname === "/" ? "/index.html" : url.pathname;
    const safePath = path.normalize(pathname).replace(/^(\.\.[/\\])+/, "");
    const filePath = path.join(dist, safePath);
    if (!filePath.startsWith(dist)) {
      return new Response("Not found", { status: 404 });
    }
    try {
      const body = await readFile(filePath);
      return new Response(body, {
        headers: { "Content-Type": types.get(path.extname(filePath)) || "application/octet-stream" },
      });
    } catch {
      const body = await readFile(path.join(dist, "index.html"));
      return new Response(body, { headers: { "Content-Type": "text/html; charset=utf-8" } });
    }
  },
});

console.log(`ControlMesh web listening on http://127.0.0.1:${port}`);
