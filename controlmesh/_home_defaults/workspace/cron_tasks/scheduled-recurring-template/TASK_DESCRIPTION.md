# Scheduled Recurring Task

## Goal

Run one stable recurring cron task and report the current result.

## Why This Exists

This template is for ordinary repeating automation:

- daily sync
- hourly health checks
- periodic report generation
- recurring audits

It is not a temporary monitor and not an externally triggered workflow.

## Boundaries

- The trigger is wall-clock schedule based.
- Each run should be independently useful.
- The task may keep task-local continuity through its memory file.
- It must not assume live foreground conversation context.

## Inputs

The task should be parameterized with:

- task scope
- runtime path or target
- expected dependencies
- not-applicable condition if relevant
- safety boundaries
- exact recurring steps

## Output Contract

Produce a compact result with:

- final state
- the current run's important facts only
- warning or error details only when actionable
