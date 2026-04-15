# Codex Hooks

This module documents ControlMesh's current view of Codex-native lifecycle support
and inspects whether a given repo is actually configured for native Codex
hooks.

Source:

- implementation: `controlmesh/cli/codex_hooks.py`

## Purpose

ControlMesh already supports the Codex CLI as a provider, but provider support does
not automatically mean lifecycle-hook support.

The `codex_hooks` module is the explicit capability matrix that answers:

- which lifecycle surfaces are native
- which are only partially native
- which still belong to ControlMesh runtime fallback
- which are not supported yet
- whether `.codex/config.toml` and `.codex/hooks.json` make native hooks
  available/configured for a specific project root

## Current Matrix Categories

- `native`
- `native_partial`
- `runtime_fallback`
- `not_supported`

## Why This Exists

Without a matrix, runtime behavior drifts into undocumented assumptions.

This module lets future work on:

- native Codex hook registration
- stop/continuation behavior
- session-start bookkeeping
- gateway-based session-end and idle delivery

land against a declared compatibility surface instead of ad hoc branching.

## Non-Goals

- It does not register Codex hooks by itself.
- It does not replace `orchestrator/hooks.py`.
- It does not yet perform runtime dispatch.

## Availability vs Configuration

The inspection helper keeps three states separate:

- `native_hooks_available`: `.codex/config.toml` exists and enables
  `[features].codex_hooks = true`
- `native_hooks_configured`: native hooks are available and `.codex/hooks.json`
  also exists
- `effective_mode`: whether ControlMesh should prefer native hooks right now or stay
  on runtime fallback, taking `codex_hooks.enabled` and `prefer_native` into
  account
