# Flow-Triggered Task

## Goal

Execute one bounded task that belongs to a specific local workflow phase.

## Why This Exists

This template is for work such as:

- release follow-up
- finalize or verify phase
- temporary migration execution
- one-off repair step owned by a larger workflow

It is not ordinary recurring automation and not an inbound webhook trigger.

## Boundaries

- The task belongs to a named workflow or phase.
- The task should stop after the bounded phase is complete.
- The result must hand control back to the owning workflow cleanly.

## Inputs

The task should be parameterized with:

- workflow or phase name
- local context and prerequisites
- success continuation instruction
- failure continuation instruction
- timeout or stop condition

## Output Contract

Produce a compact result with:

- phase executed
- final state
- what completed
- exact next step or blocker
