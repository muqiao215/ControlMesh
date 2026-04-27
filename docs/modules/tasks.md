# tasks/

Delegated background task system (`TaskHub`) for the Feishu native task runtime.

## Files

- `tasks/hub.py`: task lifecycle (submit/run/resume/question/cancel/shutdown)
- `tasks/registry.py`: persistent registry + task-folder seeding + cleanup/delete
- `tasks/models.py`: `TaskSubmit`, `TaskEntry`, `TaskInFlight`, `TaskResult`
- `orchestrator/selectors/task_selector.py`: `/tasks` UI callbacks (`tsc:*`)
- `_home_defaults/workspace/tools/task_tools/*.py`: CLI tools (`create`, `resume`, `tell`, `ask_parent`, `check_task_updates`, `list`, `cancel`, `delete`)

## Purpose

Run routable work asynchronously while keeping parent chat responsive.

The public runtime primitive surface is:

- `POST /tasks/create`
- `POST /tasks/resume`
- `POST /tasks/tell`
- `POST /tasks/ask_parent`
- `GET /tasks/list`
- `POST /interagent/send`

Capability routing is available through:

- `tools/task_tools/route_task.py`
- `/tasks/create` with `route=auto`

The MVP WorkUnit kinds are `test_execution`, `code_review`, and
`patch_candidate`. Routing fills empty provider/model/topology fields from a
capability registry and never overrides explicit values.

CLI-visible product checks:

- `controlmesh tasks list`
- `controlmesh tasks doctor`

`controlmesh tasks doctor` renders the shared task policy, including the
`>30 seconds` delegation threshold from `controlmesh.tasks.task_policy`.

In ControlMesh mode, task agents are execution workers, not judges.
They should be prompted with the pure automatic worker contract in:

- `plans/tasks/_template/worker_prompt.md`

They may produce task-local evidence and `proposed_*`, but they do not decide final outcomes or mutate canonical state.
They also do not ask the parent agent for policy or adjudication decisions in pure automatic mode.

High-level flow:

1. create (`/tasks/create`)
2. execute (`TaskHub._run`)
3. optional running-task update (`/tasks/tell`)
4. optional question (`/tasks/ask_parent`)
5. optional resume (`/tasks/resume`)
6. result delivery + parent-session injection
7. optional permanent deletion (`/tasks/delete`)

## Persistence and folders

Main-home task data:

- registry: `~/.controlmesh/tasks.json`
- folders: `~/.controlmesh/workspace/tasks/<task_id>/`

Task folder seeds include:

- task memory metadata
- provider runtime instruction files

Startup/maintenance behavior:

- stale `running` entries -> downgraded to `failed`
- orphan entries/folders are cleaned
- periodic orphan cleanup runs every 5 hours

## Config (`AgentConfig.tasks`)

- `enabled`
- `max_parallel` (per chat)
- `timeout_seconds`
- `default_topology`

## Config (`AgentConfig.agent_routing`)

- `enabled`
- `mode`
- `capability_registry`
- `score_memory_path`
- `min_confidence`

## Execution model (`TaskHub`)

`submit(TaskSubmit)`:

- resolves chat ID from `parent_agent` mapping when missing
- creates registry entry and folder
- appends mandatory task rules suffix
- spawns async execution

`_run(...)`:

- builds `AgentRequest` with `process_label=task:<task_id>`
- applies provider/model overrides when supplied
- persists resolved provider/model on first run
- updates status:
  - `done`
  - `waiting` (question asked)
  - `failed`
  - `cancelled`

Resume behavior:

- allowed from `done|failed|cancelled|waiting`
- requires stored `session_id` and provider
- keeps same `task_id` and folder

Running-task parent updates:

- allowed only while the task still has an active in-flight worker process
- stored in the task folder as an append-only inbox
- consumed by the worker via `check_task_updates.py`
- does not replace `resume`; use `resume` after `waiting|done|failed|cancelled`

## Topic-aware routing

Tasks preserve topic context:

- `TaskEntry.thread_id` stores origin topic/thread
- the task creation helper forwards `CONTROLMESH_CHAT_ID` and `CONTROLMESH_TOPIC_ID` to `/tasks/create`
- result/question envelopes map `thread_id -> topic_id`
- parent-session injection resumes the correct topic session

## InternalAgentAPI endpoints

- `POST /tasks/create`
- `POST /tasks/resume`
- `POST /tasks/tell`
- `POST /tasks/pull_updates`
- `POST /tasks/ask_parent`
- `GET /tasks/list`
- `POST /interagent/send`
- `POST /tasks/cancel`
- `POST /tasks/delete`

Behavior details:

- no task hub attached -> `503` for mutating endpoints (`/tasks/list` returns empty list)
- `/tasks/list?from=<agent>` filters by task owner
- ownership checks for `/tasks/resume`, `/tasks/tell`, `/tasks/cancel`, `/tasks/delete` when `from` is provided
- `/tasks/delete` only deletes finished tasks (`done|failed|cancelled`)

## Registry deletion semantics

`TaskRegistry.delete(task_id)`:

- returns `False` if task is missing or not in a finished state
- removes both registry entry and task folder
- resolves folder path before entry removal (prevents per-agent folder resolution bug)

Bulk cleanup path:

- `cleanup_finished(chat_id=None)` removes all finished tasks

## Telegram UX (`/tasks`)

`/tasks` is quick-command routed and renders selector UI:

- sections: Running, Waiting for answer, Finished
- callbacks (`tsc:*`): refresh, cancel one, cancel all, delete finished
- if disabled: `Task system is not enabled.`

## Tool scripts

From task agent context:

- create task
- resume task
- tell running task
- ask parent
- check task updates
- list tasks
- `cancel_task.py`
- `delete_task.py`

`delete_task.py TASK_ID` performs permanent removal of one finished task via `/tasks/delete`.
