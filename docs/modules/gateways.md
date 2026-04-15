# Gateways

This module captures the stable configuration surface for future gateway-based
event dispatch.

Sources:

- implementation: `controlmesh/gateways/config.py`
- example config: `config.example.json`

## Purpose

Cut 2 adds a transport-neutral config shape before any runtime delivery logic
exists. The point is to lock in naming, precedence, and event-routing
structure early, without prematurely wiring commands or webhooks into the bus.

## Current Scope

- named gateway targets
- command vs webhook target types
- global precedence and timeout defaults
- per-event routing rules with instruction templates
- validation that enabled rules only point at enabled gateways

## Non-Goals

- no runtime dispatch yet
- no task-hub or bus integration yet
- no provider-specific behavior

This is intentionally a configuration skeleton only.
