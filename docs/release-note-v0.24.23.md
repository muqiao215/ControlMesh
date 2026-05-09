# ControlMesh v0.24.23

- Added machine-configurable Claude root fallback via `claude_root_permission_mode`.
- Defaulted Claude root fallback to `dontAsk` when global `permission_mode=bypassPermissions` is incompatible under EUID 0.
- Preserved provider-specific permission behavior so Codex can remain in bypass while Claude uses an explicit root-safe mode.
