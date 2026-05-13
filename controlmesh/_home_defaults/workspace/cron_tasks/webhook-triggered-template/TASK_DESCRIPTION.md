# Webhook-Triggered Task

## Goal

Process one inbound event and produce the bounded result or handoff it requires.

## Why This Exists

This template is for event-driven work such as:

- CI failure triage
- PR review trigger
- inbound sync or notification processing
- external publish or status callbacks

Prefer the webhook tools when the trigger is truly external.

## Boundaries

- The trigger is event payload driven, not wall-clock driven.
- One event should produce one bounded execution.
- The task should not keep polling after the event is processed.

## Inputs

The task should be parameterized with:

- event source
- payload fields
- safety boundaries
- expected action
- success and failure handoff instructions

## Output Contract

Produce a compact result with:

- event processed
- final state
- important evidence
- exact next step when follow-up is required
