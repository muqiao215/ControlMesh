# Case-Pack

Case-pack is a stable intermediate contract for turning one successful or
failed execution story into:

- one canonical `case.json`
- one derived `timeline.md`
- one derived `lifted.md`

Contract stance:

- `case.json` is the only source of truth.
- `timeline.md` and `lifted.md` are renderer outputs, not editable fact stores.
- semantic lint is required before render output is treated as stable.

Read next:

1. [`renderer-contract.md`](renderer-contract.md)
2. [`evidence-ref-spec.md`](evidence-ref-spec.md)
3. [`../../examples/case-pack/README.md`](../../examples/case-pack/README.md)

Scriptable entrypoints:

```bash
python -m controlmesh.case_pack lint examples/case-pack/minimal/case.json
python -m controlmesh.case_pack render examples/case-pack/minimal/case.json \
  --timeline-out /tmp/timeline.md \
  --lifted-out /tmp/lifted.md
```
