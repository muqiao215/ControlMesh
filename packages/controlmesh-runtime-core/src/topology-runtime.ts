import type { RuntimeKernel, Principal, TaskSnapshot } from "./kernel";
import type { LocalRun } from "./local-task-runtime";
/** Execution owner used by orchestration; transport implementations retain their own admission/proof rules. */
export interface TopologyRuntime {
  readonly kernel: RuntimeKernel;
  readonly topologySource: "local" | "device";
  assertPrincipal(actor: Principal): void;
  enqueue(requestId: string, taskId: string, revision: number): LocalRun;
  resume(requestId: string, taskId: string, revision: number, prompt: string): TaskSnapshot;
  inspect(runId: string): LocalRun;
  parallelLimit(): number;
  queueStatus(): { queued: number; running: number };
  drain(): Promise<void>;
}
