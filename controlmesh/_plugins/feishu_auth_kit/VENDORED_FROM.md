# Bundled Plugin: feishu-auth-kit

ControlMesh treats `feishu-auth-kit` as its bundled Feishu native plugin.

- Upstream repository: `https://github.com/muqiao215/feishu-auth-kit`
- Vendored from local commit: `b2e6b4f20d6bc1182912bc4a52989c7345189aac`
- Runtime entrypoint: `python -m controlmesh._plugins.feishu_auth_kit.runner`

The standalone repository remains the source for reusable Feishu native agent
capabilities. ControlMesh includes a vendored copy so Feishu native onboarding,
auth orchestration, message-context normalization, native tool selection
contracts, card contracts, and retry contracts work as first-class built-in
plugin capabilities.
