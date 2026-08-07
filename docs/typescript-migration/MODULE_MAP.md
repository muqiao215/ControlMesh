# TypeScript Migration Module Map

| Area | Python source | TypeScript action |
|---|---|---|
| Task status and catalog rows | `controlmesh/tasks/`, `controlmesh/api/admin_read.py` | Schema and SDK types first |
| Runtime events | `controlmesh/runtime/models.py`, `controlmesh/cli/events.py` | Schema, validators, dashboard stream consumers |
| Provider runners | `controlmesh/cli/` | Keep Python; expose status/events only |
| Messaging transports | `controlmesh/messenger/` | Keep Python adapters; normalize message schemas later |
| Memory and artifacts | `controlmesh/memory/`, task artifact paths | Read-only browser and metadata schemas first |
| Workspace paths | `controlmesh/workspace/` | Manifest schema first; Python resolver remains authoritative |
| Doctor/config | `scripts/doctor_toolchain.py`, `controlmesh/config.py` | Display Python-produced diagnostics |
| Web dashboard | none yet | TypeScript can be introduced as a product layer |
