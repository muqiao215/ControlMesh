# ControlMesh Golden Fixtures

Golden fixtures compare Python reference behavior with TypeScript consumers.

Current status: Python-reference fake provider success, timeout, error, and event-order fixtures are active. Task, artifact-write, and workspace fixtures remain gates for their corresponding runtime ports.

Required critical fixtures:

- `tasks/create.basic.json`
- `tasks/resume.waiting.json`
- `tasks/tell.running.json`
- `tasks/ask_parent.basic.json`
- `providers/fake.success.json`
- `providers/fake.timeout.json`
- `providers/fake.error.json`
- `artifacts/write.basic.json`
- `workspace/path.basic.json`
