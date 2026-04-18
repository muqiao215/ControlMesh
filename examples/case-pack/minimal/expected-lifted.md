# Minimal Case
`case_id`: minimal-case

## Summary
A compact case-pack proving that case.json can lint and render two derived views.

## Questions
- **What is the source of truth?**
  - Summary: case.json must own facts while markdown files remain derived views.
  - Timeline refs: `timeline-1`
  - Turning points: `turning-derived-views`
  - Evidence: `event:event-request`

## Misconceptions
- **Markdown views are not canonical**
  - Summary: timeline.md and lifted.md should not become parallel fact stores.
  - Timeline refs: `timeline-2`
  - Turning points: `turning-derived-views`
  - Evidence: `tool:tool-render`

## Resolutions
- **Render views from the JSON source**
  - Summary: Lint the anchors first, then render stable markdown views from case.json.
  - Timeline refs: `timeline-2`
  - Turning points: `turning-derived-views`
  - Evidence: `artifact:artifact-case-json`
