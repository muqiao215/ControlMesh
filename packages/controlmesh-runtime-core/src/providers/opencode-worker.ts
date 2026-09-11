import type { Lease, Principal, RuntimeKernel, TaskSnapshot } from "../kernel";
import { ProcessSupervisor } from "../process-supervisor";
import { digest, requireThat } from "../value";
import { nativeTaskDigest } from "./native-manifest";
import { NativeSessionStore } from "./native-session";
import { PreflightCache, type ProbeBinding } from "./preflight-cache";
import { OpenCodeExecution, type IssuedReadAdmission, type OpenCodeWorkerConfig, type NativeRunner } from "./opencode-execution";
export type { IssuedReadAdmission, OpenCodeWorkerConfig } from "./opencode-execution";

/** Coordinator-local adapter. The shared native driver also supports a distinct authenticated device adapter. */
export class OpenCodeWorker {
  private readonly execution: OpenCodeExecution;
  constructor(private readonly kernel: RuntimeKernel, private readonly cache: PreflightCache,
    store: NativeSessionStore, config: OpenCodeWorkerConfig, runner: NativeRunner = new ProcessSupervisor()) {
    this.execution = new OpenCodeExecution(store, config, runner);
  }

  async execute(actor: Principal, lease: Lease, binding: ProbeBinding, admission: IssuedReadAdmission, timeoutMs = 60_000,
    lifecycle: { signal?: AbortSignal; remainingMs?: () => number } = {}): Promise<TaskSnapshot> {
    requireThat(actor.origin === "human_request", "source_execution_floor_unavailable");
    const task = this.kernel.inspect(actor, lease.task_id).task, issued = nativeTaskDigest(task);
    const request = (operation: string) => `native-${digest([lease.episode_id, operation])}`;
    const effect = `native-${lease.episode_id}`;
    let dispatched = false;
    const assertCurrent = () => {
      this.kernel.withLease(actor, lease, () => {});
      requireThat(nativeTaskDigest(this.kernel.inspect(actor, lease.task_id).task) === issued, "worker_task_binding_changed");
    };
    try {
      return await this.execution.execute(task, binding, admission, {
        ...lifecycle,
        assertCurrent,
        assertReady: () => { this.cache.assertReady(actor, binding); },
        preflightGeneration: () => this.cache.inspect(actor, binding).generation!,
        executionFailure: (generation, failure) => { this.cache.recordExecutionFailure(actor, binding, generation, failure); },
        dispatch: (intent, manifest) => {
          const permit = this.kernel.db.transaction(() => {
            assertCurrent();
            this.kernel.start(actor, request("start"), lease);
            return this.kernel.dispatchEffect(actor, request("dispatch"), lease, effect, intent, manifest);
          });
          dispatched = permit.dispatch_permitted;
          return dispatched;
        },
        observe: observation => { this.kernel.recordEffectObservation(actor, request("observe"), lease, effect, observation); },
        complete: result => this.kernel.db.transaction(() => {
          this.kernel.confirmEffect(actor, request("confirm"), lease, effect, result);
          return this.kernel.finish(actor, request("finish"), lease, "done", result);
        }),
      }, timeoutMs);
    } catch (error) {
      if (dispatched) {
        const reason = error instanceof Error && /^[a-z0-9_]{1,96}$/.test(error.message) ? error.message : "native_worker_failure";
        try { this.kernel.markUnknown(actor, request("unknown"), lease, reason); } catch { /* the current owner or cancellation remains authoritative */ }
      }
      throw error;
    }
  }
}
