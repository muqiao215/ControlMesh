# Evidence Ref Spec

`evidence_refs` are stable anchors from narrative objects back to factual
objects inside `case.json`.

## Anchor Syntax

Format:

```text
<prefix>:<id>
```

Official prefixes:

- `msg:<message_id>`
- `event:<event_id>`
- `tool:<tool_event_id>`
- `artifact:<artifact_id>`
- `link:<link_id>`

## What These Anchors Target

- `msg:` points to `messages[].id`
- `event:` points to `events[].id`
- `tool:` points to `tool_events[].id`
- `artifact:` points to `artifacts[].id`
- `link:` points to `links[].id`

## Allowed Mount Points

`evidence_refs` may appear on:

- `artifacts[]`
- `events[]`
- `tool_events[]`
- `timeline[]`
- `turning_points[]`
- `lifted_view.questions[]`
- `lifted_view.misconceptions[]`
- `lifted_view.resolutions[]`

## View-Layer Preservation Rules

- `timeline[].id` and `turning_points[].id` are view-layer IDs, not evidence anchors.
- Lifted items back-reference those view-layer IDs through:
  - `timeline_refs`
  - `turning_point_refs`
- Renderers must preserve evidence anchors exactly as written.
- Renderers may format anchors as inline code, but may not rename or normalize them.

## Non-Goals

- `evidence_refs` do not point to free-form markdown sections.
- `evidence_refs` do not point to local absolute filesystem paths.
- Derived markdown files are not valid evidence targets.
