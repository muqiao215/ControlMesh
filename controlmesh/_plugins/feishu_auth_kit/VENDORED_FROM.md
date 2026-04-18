# Bundled Plugin: feishu-auth-kit

ControlMesh treats `feishu-auth-kit` as its bundled Feishu native plugin.

- Upstream repository: `https://github.com/muqiao215/feishu-auth-kit`
- Vendored from local commit: `2e4d41e143dbd0b7ee92e0b00c467baaa3ee7daa`
- Runtime entrypoint: `python -m controlmesh._plugins.feishu_auth_kit.runner`

The standalone repository remains the source for reusable Feishu native agent
capabilities. ControlMesh includes a vendored copy so Feishu native onboarding,
auth orchestration, message-context normalization, native tool selection
contracts, native tool registry/spec/scopes, card contracts, and retry
contracts work as first-class built-in plugin capabilities.
