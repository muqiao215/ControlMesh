# pwf_wave

`pwf_wave` is the planned file-driven overnight work topology.

It is not implemented as a runtime topology yet. The intended loop is:

```text
controller writes task_plan/findings/progress
worker executes one phase and writes evidence
evaluator accepts/rejects
controller promotes or schedules hardening
repeat until stop condition
```

This should build on the routing plane:

- classify each phase as a WorkUnit
- route workers by capability
- keep worker evidence task-local
- let controller/evaluator decide promotion

The MVP in this branch only implements `test_execution`, `code_review`, and
`patch_candidate` routing. `pwf_wave` should come after those contracts are
stable.
