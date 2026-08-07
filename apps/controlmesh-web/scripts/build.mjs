import { mkdir, copyFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const dist = path.join(root, "dist");
const assets = path.join(dist, "assets");

await mkdir(assets, { recursive: true });

const result = await Bun.build({
  entrypoints: [path.join(root, "src/main.ts")],
  outdir: assets,
  target: "browser",
  format: "esm",
  naming: "main.js",
});

if (!result.success) {
  for (const log of result.logs) {
    console.error(log);
  }
  process.exit(1);
}

await copyFile(path.join(root, "src/styles.css"), path.join(assets, "styles.css"));
await writeFile(
  path.join(dist, "index.html"),
  `<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>ControlMesh</title>
    <link rel="stylesheet" href="/assets/styles.css" />
  </head>
  <body>
    <main id="app"></main>
    <script type="module" src="/assets/main.js"></script>
  </body>
</html>
`,
);
