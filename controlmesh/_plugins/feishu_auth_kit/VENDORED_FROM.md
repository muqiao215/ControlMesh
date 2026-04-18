# Bundled Plugin: feishu-auth-kit

ControlMesh treats `feishu-auth-kit` as its bundled Feishu native plugin.

- Upstream repository: `https://github.com/muqiao215/feishu-auth-kit`
- Vendored from local commit: `0d80f4369d066faba6b9ad47235a0fc142d01281`
- Runtime entrypoint: `python -m controlmesh._plugins.feishu_auth_kit.runner`

The standalone repository remains the source for reusable Feishu native agent
capabilities. ControlMesh includes a vendored copy so Feishu native onboarding,
auth orchestration, message-context normalization, card contracts, and retry
contracts work as first-class built-in plugin capabilities.
