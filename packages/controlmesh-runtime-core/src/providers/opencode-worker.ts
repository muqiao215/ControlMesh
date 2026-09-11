import type { Lease, Principal, RuntimeKernel, TaskSnapshot } from "../kernel";
import { ProcessSupervisor } from "../process-supervisor";
import { digest, requireThat } from "../value";
import { nativeTaskDigest } from "./native-manifest";
import { NativeSessionStore } from "./native-session";
import { PreflightCache, type ProbeBinding } from "./preflight-cache";
import { OpenCodeExecution, type IssuedReadAdmission, type OpenCodeWorkerConfig, type NativeRunner } from "./opencode-execution";
import { NativeMailboxDelivery } from "./native-mailbox";
import { NativeAgentBroker } from "./native-agent-broker";
import { NativeAgentJournal, type NativeAgentToolResult } from "./native-agent-journal";
import type { LocalExecutionContext } from "../local-task-runtime";
export type { IssuedReadAdmission, OpenCodeWorkerConfig } from "./opencode-execution";

/** Coordinator-local adapter. The shared native driver also supports a distinct authenticated device adapter. */
export class OpenCodeWorker {
  private readonly execution: OpenCodeExecution;
  constructor(private readonly kernel: RuntimeKernel, private readonly cache: PreflightCache,
    store: NativeSessionStore, private readonly config: OpenCodeWorkerConfig, runner: NativeRunner = new ProcessSupervisor()) {
    this.execution = new OpenCodeExecution(store, config, runner);
  }

  async execute(actor: Principal, lease: Lease, binding: ProbeBinding, admission: IssuedReadAdmission, timeoutMs = 60_000,
    lifecycle: Partial<Omit<LocalExecutionContext, "assertCurrent">> = {}): Promise<TaskSnapshot> {
    requireThat(actor.origin === "human_request", "source_execution_floor_unavailable");
    const task = this.kernel.inspect(actor, lease.task_id).task, issued = nativeTaskDigest(task);
    const request = (operation: string) => `native-${digest([lease.episode_id, operation])}`;
    const effect = `native-${lease.episode_id}`;
    const mailbox = new NativeMailboxDelivery(this.kernel);
    const delivery = mailbox.prepare(actor, lease, task.prompt as string);
    let dispatched = false;
    const assertCurrent = () => {
      this.kernel.withLease(actor, lease, () => {});
      requireThat(nativeTaskDigest(this.kernel.inspect(actor, lease.task_id).task) === issued, "worker_task_binding_changed");
    };
    const publicationCurrent = () => {
      assertCurrent(); requireThat(!lifecycle.signal?.aborted, "native_execution_cancelled");
      const response: unknown = (lifecycle.assertPublicationAuthority ?? admission.assertCurrent)();
      if (response !== undefined) { void Promise.resolve(response).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
    };
    const communication = this.config.communication ? new NativeAgentBroker(this.kernel, actor, lease, effect, this.config.communication,
      () => {
        assertCurrent();
        const checked: unknown = admission.assertCurrent();
        if (checked !== undefined) { void Promise.resolve(checked).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
        requireThat(!lifecycle.signal?.aborted, "native_agent_execution_cancelled");
      }) : null;
    const journal = new NativeAgentJournal(this.kernel);
    let nativeTools: NativeAgentToolResult[] = [];
    try {
      await communication?.start();
      return await this.execution.execute(task, binding, admission, {
        ...lifecycle,
        ...(admission.workspace_write ? { workspace: { state_home: this.config.state_home,
          binding_digest: digest({ lease, task: issued, binding }), assertCurrent: publicationCurrent,
          authority: <R>(operation: () => R): R => this.kernel.withLease(actor, lease, () => { publicationCurrent(); return operation(); }),
          verifyPublication: lifecycle.verifyPublication } } : {}),
        mailbox_delivery: delivery,
        ...(communication ? { communication: { scope: communication.scope, command: communication.command, freeze: () => communication.close(),
          verify: (tools: NativeAgentToolResult[]) => {
            const proof = journal.verify(effect, communication.scope, tools); nativeTools = structuredClone(tools); return proof;
          } } } : {}),
        assertCurrent,
        assertReady: () => { this.cache.assertReady(actor, binding); },
        preflightGeneration: () => this.cache.inspect(actor, binding).generation!,
        executionFailure: (generation, failure) => { this.cache.recordExecutionFailure(actor, binding, generation, failure); },
        dispatch: (intent, manifest) => {
          const permit = this.kernel.db.transaction(() => {
            assertCurrent();
            this.kernel.start(actor, request("start"), lease);
            const permit = this.kernel.dispatchEffect(actor, request("dispatch"), lease, effect, intent, manifest);
            if (permit.dispatch_permitted && delivery) mailbox.reserve(actor, lease, effect, delivery);
            return permit;
          });
          dispatched = permit.dispatch_permitted;
          return dispatched;
        },
        observe: observation => { this.kernel.recordEffectObservation(actor, request("observe"), lease, effect, observation); },
        complete: result => this.kernel.db.transaction(() => {
          if (delivery) mailbox.consume(actor, lease, effect, delivery, result);
          if (communication) journal.consume(actor, lease, effect, communication.scope, nativeTools);
          const accepted = { ...result, mailbox_pending_count: mailbox.pendingCount(actor, lease.task_id) };
          this.kernel.confirmEffect(actor, request("confirm"), lease, effect, accepted);
          return this.kernel.finish(actor, request("finish"), lease, "done", accepted);
        }),
      }, timeoutMs);
    } catch (error) {
      if (dispatched) {
        const reason = error instanceof Error && /^[a-z0-9_]{1,96}$/.test(error.message) ? error.message : "native_worker_failure";
        try { this.kernel.markUnknown(actor, request("unknown"), lease, reason); } catch { /* the current owner or cancellation remains authoritative */ }
      }
      throw error;
    } finally { await communication?.close(); }
  }
}
