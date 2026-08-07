/** Internal-only task lifecycle candidate and parity gate. Never transport-facing. */

export const lifecycleDomains = [
  "create",
  "tell",
  "ask_parent",
  "resume",
  "cancel",
  "recovery",
  "workspace",
  "artifact",
] as const;

export type LifecycleDomain = (typeof lifecycleDomains)[number];

export interface LifecycleCase {
  id: string;
  domain: LifecycleDomain;
  operation: string;
  input: Record<string, unknown>;
  expected: Record<string, unknown>;
}

export interface LifecycleMatrix {
  schema_version: "controlmesh.task_lifecycle_golden.v2";
  oracle: "python";
  normalizers: string[];
  required_domains: LifecycleDomain[];
  cases: LifecycleCase[];
}

export interface LifecycleObservation {
  id: string;
  domain: LifecycleDomain;
  operation: string;
  actual: Record<string, unknown>;
}

export interface LifecycleDiff {
  case_id: string;
  path: string;
  expected: unknown;
  actual: unknown;
}

export interface LifecycleParityReport {
  schema_version: "controlmesh.lifecycle_parity_report.v1";
  matrix_schema_version: LifecycleMatrix["schema_version"];
  required_domains: LifecycleDomain[];
  case_count: number;
  matched_case_count: number;
  missing_case_ids: string[];
  extra_case_ids: string[];
  diffs: LifecycleDiff[];
  status: "pass" | "fail";
}

interface CandidateTask {
  task_id: string;
  status: string;
  provider: string;
  model: string;
  session_id: string;
  thinking: string;
  transport: string;
  chat_id: number;
  thread_id: number;
  last_question: string;
  question_count: number;
}

function string(input: Record<string, unknown>, key: string): string {
  const value = input[key];
  return typeof value === "string" ? value : "";
}

function number(input: Record<string, unknown>, key: string): number {
  const value = input[key];
  return typeof value === "number" ? value : 0;
}

function bool(input: Record<string, unknown>, key: string): boolean {
  return input[key] === true;
}

function error(type: string, message: string): Record<string, string> {
  return { type, message };
}

/**
 * Candidate semantics are deliberately in-memory. They prove contract parity while Python
 * remains the only implementation allowed to mutate persisted production state.
 */
export class InternalTaskLifecycleFacade {
  #tasks = new Map<string, CandidateTask>();
  #updates = new Map<string, Array<Record<string, unknown>>>();

  execute(testCase: LifecycleCase): LifecycleObservation {
    const actual = this.#execute(testCase);
    return { id: testCase.id, domain: testCase.domain, operation: testCase.operation, actual };
  }

  #execute(testCase: LifecycleCase): Record<string, unknown> {
    const input = testCase.input;
    switch (testCase.id) {
      case "create.basic":
        return this.#create(input);
      case "tell.running":
      case "tell.not_running":
        return this.#tell(input);
      case "ask_parent.basic":
      case "ask_parent.missing":
        return this.#askParent(input);
      case "resume.waiting":
      case "resume.no_session":
        return this.#resume(input);
      case "cancel.running":
      case "cancel.missing":
        return this.#cancel(input);
      case "recovery.restart_stale":
        return this.#recover(input);
      case "workspace.custom_tasks_dir":
        return this.#workspace(input);
      case "artifact.read":
      case "artifact.traversal":
      case "artifact.missing_task":
        return this.#artifact(input);
      default:
        throw new Error(`Unsupported lifecycle parity case '${testCase.id}'`);
    }
  }

  #create(input: Record<string, unknown>): Record<string, unknown> {
    const task: CandidateTask = {
      task_id: string(input, "task_id"),
      status: "running",
      provider: string(input, "provider"),
      model: string(input, "model"),
      session_id: "",
      thinking: string(input, "thinking"),
      transport: string(input, "transport"),
      chat_id: number(input, "chat_id"),
      thread_id: number(input, "thread_id"),
      last_question: "",
      question_count: 0,
    };
    this.#tasks.set(task.task_id, task);
    return {
      task: {
        task_id: task.task_id,
        status: task.status,
        provider: task.provider,
        model: task.model,
        thinking: task.thinking,
        transport: task.transport,
        chat_id: task.chat_id,
        thread_id: task.thread_id,
      },
      seeded_files: [
        "AGENTS.md",
        "CLAUDE.md",
        "EVIDENCE.json",
        "GEMINI.md",
        "RESULT.md",
        "TASKMEMORY.md",
        "WORKUNIT.json",
        "events.jsonl",
      ],
      event_types: ["task.folder.seeded"],
    };
  }

  #tell(input: Record<string, unknown>): Record<string, unknown> {
    const taskId = string(input, "task_id");
    if (!bool(input, "in_flight")) {
      return { error: error("ValueError", `Task '${taskId}' is not currently running`) };
    }
    const updates = this.#updates.get(taskId) ?? [];
    const update: Record<string, unknown> = {
      sequence: updates.length + 1,
      message: string(input, "message"),
      sent_at: string(input, "sent_at"),
    };
    const parentAgent = string(input, "parent_agent");
    if (parentAgent) update.from = parentAgent;
    updates.push(update);
    this.#updates.set(taskId, updates);
    return { sequence: update.sequence, updates };
  }

  #askParent(input: Record<string, unknown>): Record<string, unknown> {
    const taskId = string(input, "task_id");
    const task = this.#tasks.get(taskId);
    if (!task) return { response: "Error: Task not found" };
    if (!bool(input, "handler_registered")) {
      return { response: "Error: No question handler for agent 'main'" };
    }
    task.question_count += 1;
    task.last_question = string(input, "question").slice(0, 200);
    return {
      response:
        "Question forwarded to parent agent. Finish your current work — you will be resumed with the answer.",
      question_count: task.question_count,
      last_question: task.last_question,
      delivery_count: 1,
    };
  }

  #resume(input: Record<string, unknown>): Record<string, unknown> {
    const taskId = string(input, "task_id");
    const sessionId = string(input, "session_id");
    if (!sessionId) {
      return { error: error("ValueError", `Task '${taskId}' has no resumable session`) };
    }
    const task = this.#tasks.get(taskId) ?? {
      task_id: taskId,
      status: string(input, "from_status"),
      provider: string(input, "provider"),
      model: string(input, "model"),
      session_id: sessionId,
      thinking: "",
      transport: "",
      chat_id: 0,
      thread_id: 0,
      last_question: "",
      question_count: 0,
    };
    task.status = "running";
    task.provider = string(input, "provider") || task.provider;
    task.model = string(input, "model") || task.model;
    task.session_id = sessionId;
    task.last_question = "";
    this.#tasks.set(taskId, task);
    return {
      returned_task_id: taskId,
      same_task_id: true,
      status: task.status,
      provider: task.provider,
      model: task.model,
      session_id: task.session_id,
      last_question: task.last_question,
      error: "",
    };
  }

  #cancel(input: Record<string, unknown>): Record<string, unknown> {
    return { cancelled: bool(input, "exists") && bool(input, "in_flight") };
  }

  #recover(input: Record<string, unknown>): Record<string, unknown> {
    const running = ["running", "recovering"].includes(string(input, "persisted_status"));
    return {
      status: running ? "stale" : string(input, "persisted_status"),
      error: running ? "Bot restarted while detached task state was unresolved" : "",
      task_id_preserved: bool(input, "folder_exists"),
    };
  }

  #workspace(input: Record<string, unknown>): Record<string, unknown> {
    const tasksDir = string(input, "tasks_dir");
    const taskId = string(input, "task_id");
    return {
      tasks_dir: tasksDir,
      task_folder: `${tasksDir}/${taskId}`,
      default_folder_used: tasksDir === string(input, "default_tasks_dir"),
    };
  }

  #artifact(input: Record<string, unknown>): Record<string, unknown> {
    const taskId = string(input, "task_id");
    const relativePath = string(input, "relative_path");
    if (relativePath.split("/").some((part) => part === ".." || part === "." || part === "")) {
      return { error: error("InvalidArtifactPathError", "artifact path is invalid") };
    }
    if (taskId === "missing-task") {
      return { error: error("ArtifactNotFoundError", "artifact not found") };
    }
    const content = string(input, "content");
    const name = relativePath.split("/").at(-1) ?? "";
    return {
      relative_path: relativePath,
      name,
      mime: name.endsWith(".txt") ? "text/plain" : "application/octet-stream",
      size: new TextEncoder().encode(content).byteLength,
      content,
    };
  }
}

export function parseLifecycleMatrix(raw: unknown): LifecycleMatrix {
  if (!raw || typeof raw !== "object") throw new Error("Lifecycle matrix must be an object");
  const matrix = raw as Partial<LifecycleMatrix>;
  if (matrix.schema_version !== "controlmesh.task_lifecycle_golden.v2") {
    throw new Error("Unsupported lifecycle matrix schema_version");
  }
  if (matrix.oracle !== "python" || !Array.isArray(matrix.cases)) {
    throw new Error("Lifecycle matrix must use the Python oracle and contain cases");
  }
  if (!Array.isArray(matrix.required_domains)) throw new Error("Lifecycle domains are missing");
  const ids = new Set<string>();
  for (const value of matrix.cases) {
    if (!value || typeof value.id !== "string" || typeof value.operation !== "string") {
      throw new Error("Lifecycle matrix contains an invalid case");
    }
    if (!lifecycleDomains.includes(value.domain)) throw new Error(`Invalid domain '${value.domain}'`);
    if (ids.has(value.id)) throw new Error(`Duplicate lifecycle case '${value.id}'`);
    if (!value.input || !value.expected) throw new Error(`Lifecycle case '${value.id}' is incomplete`);
    ids.add(value.id);
  }
  return matrix as LifecycleMatrix;
}

export function runLifecycleCandidate(matrix: LifecycleMatrix): LifecycleObservation[] {
  const facade = new InternalTaskLifecycleFacade();
  return matrix.cases.map((testCase) => facade.execute(testCase));
}

function compare(expected: unknown, actual: unknown, path: string, caseId: string): LifecycleDiff[] {
  if (Object.is(expected, actual)) return [];
  if (Array.isArray(expected) && Array.isArray(actual)) {
    const diffs: LifecycleDiff[] = [];
    const length = Math.max(expected.length, actual.length);
    for (let index = 0; index < length; index += 1) {
      diffs.push(...compare(expected[index], actual[index], `${path}/${index}`, caseId));
    }
    return diffs;
  }
  if (expected && actual && typeof expected === "object" && typeof actual === "object") {
    const expectedObject = expected as Record<string, unknown>;
    const actualObject = actual as Record<string, unknown>;
    const keys = [...new Set([...Object.keys(expectedObject), ...Object.keys(actualObject)])].sort();
    return keys.flatMap((key) =>
      compare(expectedObject[key], actualObject[key], `${path}/${key}`, caseId),
    );
  }
  return [{ case_id: caseId, path, expected, actual }];
}

export function diffLifecycleParity(
  matrix: LifecycleMatrix,
  observations: LifecycleObservation[],
): LifecycleParityReport {
  const byId = new Map(observations.map((observation) => [observation.id, observation]));
  const expectedIds = new Set(matrix.cases.map((testCase) => testCase.id));
  const missing = matrix.cases.filter((testCase) => !byId.has(testCase.id)).map((testCase) => testCase.id);
  const extra = observations.filter((item) => !expectedIds.has(item.id)).map((item) => item.id);
  const diffs = matrix.cases.flatMap((testCase) => {
    const observation = byId.get(testCase.id);
    return observation ? compare(testCase.expected, observation.actual, "", testCase.id) : [];
  });
  const matched = matrix.cases.length - new Set(diffs.map((diff) => diff.case_id)).size - missing.length;
  return {
    schema_version: "controlmesh.lifecycle_parity_report.v1",
    matrix_schema_version: matrix.schema_version,
    required_domains: matrix.required_domains,
    case_count: matrix.cases.length,
    matched_case_count: matched,
    missing_case_ids: missing,
    extra_case_ids: extra,
    diffs,
    status: missing.length || extra.length || diffs.length ? "fail" : "pass",
  };
}
