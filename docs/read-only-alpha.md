# Read-only Alpha

ControlMesh `0.42.0a1` is the first installable Alpha of the authenticated read-only
facade and local dashboard. It reads existing local task history, events, providers,
topologies, and artifact metadata/content. It does not create, tell, resume, cancel, or
otherwise mutate tasks.

## Install Alongside Stable

Requirements: Python 3.11+ and `pipx`.

```bash
pipx install --suffix=-alpha "controlmesh[api]==0.42.0a1"
controlmesh-alpha version
```

The expected version is `0.42.0a1`. The `-alpha` suffix keeps an existing stable install
untouched.

## Start

```bash
controlmesh-alpha api serve
```

The command:

- binds only to `127.0.0.1:8741`;
- reads the existing ControlMesh home selected by `CONTROLMESH_HOME` or the normal path
  resolver;
- prints an ephemeral bearer token unless `CONTROLMESH_API_TOKEN` is set;
- serves the API at `http://127.0.0.1:8741/api/v1`;
- serves the bundled dashboard at `http://127.0.0.1:8741/dashboard/`.

Open the dashboard URL, paste the printed token, and select **Refresh**. The token is kept
in browser local storage, so use a dedicated local browser profile if that matters for
your threat model.

To choose another local port or a repeatable token:

```bash
CONTROLMESH_API_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')" \
  controlmesh-alpha api serve --port 8877
```

The Alpha intentionally rejects non-loopback `--host` values.

## Verify With HTTP

Use the token printed by the server:

```bash
export CONTROLMESH_ALPHA_TOKEN="replace-with-printed-token"
curl --fail \
  -H "Authorization: Bearer $CONTROLMESH_ALPHA_TOKEN" \
  http://127.0.0.1:8741/api/v1/tasks
```

Supported read-only routes:

- `GET /api/v1/tasks`
- `GET /api/v1/tasks/{task_id}`
- `GET /api/v1/tasks/{task_id}/events`
- `GET /api/v1/tasks/{task_id}/artifacts`
- `GET /api/v1/tasks/{task_id}/artifacts/content?relative_path=...`
- `GET /api/v1/providers`
- `GET /api/v1/topologies`

Artifact requests use the exact relative path returned by metadata. Absolute paths,
client-constructed private paths, and symlink escapes are not supported.

## SDK From This Repository

The TypeScript packages remain private Alpha workspace packages. From a source checkout:

```bash
pnpm install --frozen-lockfile
```

```ts
import { ControlMeshClient } from "@controlmesh/sdk";

const client = new ControlMeshClient({
  baseUrl: "http://127.0.0.1:8741",
  token: process.env.CONTROLMESH_ALPHA_TOKEN,
});

const tasks = await client.listTasks({ limit: 20 });
const providers = await client.getProviderStatus();
```

The Alpha SDK exports only supported read methods. Task mutation remains Python-owned and
is not a public SDK capability.

## Stop and Remove

Press `Ctrl+C` in the server terminal, then optionally remove the side-by-side install:

```bash
pipx uninstall controlmesh-alpha
```

## Limitations

- Localhost only; no remote browser deployment contract exists yet.
- Browser credential storage and operator scopes are not finalized.
- The dashboard is read-only and does not replace terminal/chat task control.
- This is an Alpha. Keep the stable installation for production runtime use.
