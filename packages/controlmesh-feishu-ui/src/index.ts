import type { Task } from "@controlmesh/protocol";

export interface FeishuCard {
  schema: "2.0";
  config: Record<string, unknown>;
  body: Record<string, unknown>;
}

export function renderTaskSummaryCard(task: Task): FeishuCard {
  return {
    schema: "2.0",
    config: { update_multi: true },
    body: {
      direction: "vertical",
      elements: [
        { tag: "markdown", content: `**${task.name || task.task_id}**` },
        { tag: "markdown", content: `Status: ${task.status}` },
        { tag: "markdown", content: `Provider: ${task.provider || "unknown"}` },
      ],
    },
  };
}
