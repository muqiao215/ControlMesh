# Case-Pack Examples

`case.json` is the only source of truth. `expected-timeline.md` and
`expected-lifted.md` are renderer outputs kept as golden files.

- `minimal/`: smallest complete contract fixture.
- `public-repo-release-gate/`: sanitized real case from the public release of
  `muqiao215/public-repo-release-gate`.

Validate and render:

```bash
python -m controlmesh.case_pack lint examples/case-pack/minimal/case.json
python -m controlmesh.case_pack render examples/case-pack/minimal/case.json \
  --timeline-out /tmp/timeline.md \
  --lifted-out /tmp/lifted.md
```
