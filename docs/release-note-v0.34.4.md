# ControlMesh v0.34.4

- Persist cron/webhook local runtime artifacts from ControlMesh itself instead of relying on the model to create them.
- Always write `cron_tasks/<task>/output/last_run.json` after one-shot task execution.
- Reduce cross-host cron fragility when provider tool permissions are narrower than expected.
