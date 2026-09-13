import type { ToolGrantSnapshot } from "./execution-grants";
import { digest, requireThat } from "./value";

export interface ControllerApprovalPermit {
  readonly task_id: string; readonly provider: string; readonly grant_digest: string; readonly approval_digest: string;
}
const permits = new WeakMap<object, () => void>();
/** Trusted receipt verifier only. Plain serialized task data never constitutes a permit. */
export function issueControllerApprovalPermit(taskId: string, provider: string, grant: ToolGrantSnapshot,
  approvalDigest: string, assertCurrent: () => void): ControllerApprovalPermit {
  const result: unknown = assertCurrent();
  if (result !== undefined) { void Promise.resolve(result).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
  const permit = Object.freeze({ task_id: taskId, provider, grant_digest: digest(grant), approval_digest: approvalDigest });
  permits.set(permit, assertCurrent); return permit;
}
export function assertControllerApprovalPermit(permit: ControllerApprovalPermit, taskId: string,
  provider: string, grant: ToolGrantSnapshot): void {
  const check = permits.get(permit);
  requireThat(check && permit.task_id === taskId && permit.provider === provider && permit.grant_digest === digest(grant), "controller_approval_unproven");
  const result: unknown = check();
  if (result !== undefined) { void Promise.resolve(result).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
}
