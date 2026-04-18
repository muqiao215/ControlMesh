# Minimal Case
`case_id`: minimal-case

## Summary
A compact case-pack proving that case.json can lint and render two derived views.

## Timeline
1. **Request arrives** (`event:event-request`)
   - Summary: The case begins with a request for a stable case-pack intermediate format.
   - Evidence: `event:event-request`, `msg:msg-user-request`
2. **Derived views render** (`tool:tool-render`)
   - Summary: The renderer produces timeline and lifted markdown from case.json.
   - Evidence: `tool:tool-render`, `artifact:artifact-case-json`

## Turning Points
- **Derived views stop being manual facts** (`turning_point:turning-derived-views`)
  - Summary: The decisive move is to make rendered markdown reproducible from case.json.
  - Events: `event:event-contract-set`
  - Tool events: `tool:tool-render`
  - Evidence: `event:event-contract-set`, `tool:tool-render`
