# Renderer Contract

Renderer contract for ControlMesh case-pack:

## Canonical Input

- Input is exactly one `case.json`.
- Renderers may not invent facts absent from `case.json`.
- Renderers may reorder only by explicit `timeline[].order`.

## Required Derived Views

- `timeline.md`
  - includes case title, `case_id`, summary
  - renders `timeline[]` in continuous order
  - renders turning points after the timeline
- `lifted.md`
  - includes case title, `case_id`, summary
  - renders `lifted_view.questions`
  - renders `lifted_view.misconceptions`
  - renders `lifted_view.resolutions`

## Stability Rules

- Timeline entry order is determined only by `timeline[].order`.
- Timeline and lifted renderers must preserve anchor IDs verbatim in output.
- Renderers must not silently drop a kept tool event if it is referenced by
  `timeline` or `turning_points`.
- Markdown outputs are considered golden outputs and can be snapshot-tested.

## Semantic Preconditions

Render should happen only after semantic lint passes:

- `evidence_refs` resolve to real objects
- `tool_events[].linked_event_ids` resolve to real events
- `timeline[].order` is continuous
- every turning point references an event or tool event
- every lifted item references timeline entries or turning points
