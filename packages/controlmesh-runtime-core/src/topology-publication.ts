import type { Principal, RuntimeKernel } from "./kernel";
import type { TaskCompletion } from "./task-completion";
import { WorkspaceStage, type WorkspaceAuthority } from "./workspace-stage";
import { snapshotReads } from "./providers/native-manifest";
import { dirname, join } from "node:path";
import { canonical, digest, requireThat } from "./value";

interface Row {
  task_id: string; execution_id: string; binding: string; stage_path: string; reference: string;
  witness_digest: string | null; proposal_digest: string | null; phase: "baseline" | "staged" | "applied" | "satisfied";
}
export interface PublicationFile { path: string; sha256: string; load(): Buffer }
/** Owns the gap between accepted remote bytes and canonical files; WorkspaceStage owns durable file replacement. */
export class TopologyPublication {
  constructor(private readonly kernel: RuntimeKernel, private readonly workspace: string,
    private readonly stateRoot: string, private readonly profile: string) {
    WorkspaceStage.assertLocation(stateRoot, workspace);
  }
  private binding(actor: Principal, task: string, revision: number, contract: TaskCompletion) {
    return digest({ principal: actor.id, device: actor.device_id, task, revision, contract, profile: this.profile });
  }
  private row(task: string, execution: string) {
    return this.kernel.db.sql.query("SELECT * FROM topology_artifact_publications WHERE task_id=? AND execution_id=?")
      .get(task, execution) as Row | null;
  }
  /** Called inside the scheduler transaction, before any child assignment becomes visible. */
  step(actor: Principal, task: string, revision: number, contract: TaskCompletion, execution: string | null,
    run: () => void, resultingExecution: () => string, authority: WorkspaceAuthority): void {
    const paths = contract.files.filter(file => file.mode === "write").map(file => file.path);
    if (!paths.length) { run(); return; }
    const binding = this.binding(actor, task, revision, contract), existing = execution ? this.row(task, execution) : null;
    if (existing) { requireThat(existing.binding === binding, "topology_publication_binding_changed"); run(); return; }
    requireThat(!this.kernel.db.sql.query("SELECT 1 FROM topology_tasks WHERE parent_id=? AND (? IS NULL OR execution_id=?)")
      .get(task, execution, execution), "topology_publication_baseline_missing");
    const stage = WorkspaceStage.createFiles(this.stateRoot, this.workspace, paths, binding, authority);
    run();
    this.kernel.db.sql.query("INSERT INTO topology_artifact_publications VALUES (?,?,?,?,?,NULL,NULL,'baseline')")
      .run(task, resultingExecution(), binding, stage.path, canonical(stage.reference()));
  }
  publish(actor: Principal, task: string, revision: number, execution: string, contract: TaskCompletion,
    witnesses: string, files: PublicationFile[], authority: WorkspaceAuthority) {
    const row = this.row(task, execution);
    requireThat(row && row.binding === this.binding(actor, task, revision, contract), "topology_publication_baseline_missing");
    requireThat(row.witness_digest === null || row.witness_digest === witnesses, "topology_publication_witness_changed");
    const reference = JSON.parse(row.reference);
    requireThat(dirname(row.stage_path) === this.stateRoot && reference.binding_digest === row.binding, "topology_publication_stage_changed");
    let stage = WorkspaceStage.open(row.stage_path, reference);
    const scope = stage.fileScope(), targets = contract.files.filter(file => file.mode === "write").map(file => file.path);
    requireThat(scope.workspace === this.workspace && scope.roots.every(path => targets.some(file => join(this.workspace, file) === path)), "topology_publication_stage_changed");
    const matches = (file: PublicationFile) => {
      try { return snapshotReads(this.workspace, [join(this.workspace, file.path)])[0]?.sha256 === file.sha256; }
      catch (error) { if ((error as NodeJS.ErrnoException).code === "ENOENT") return false; throw error; }
    };
    if (row.phase === "satisfied") { authority(() => { requireThat(files.every(matches), "topology_publication_content_changed"); }); return; }
    if (stage.publicationState().phase === "prepared") {
      const pending = files.filter(file => !matches(file));
      if (pending.length === 0) {
        authority(() => {
          requireThat(files.every(matches), "topology_publication_content_changed");
          this.kernel.db.sql.query("UPDATE topology_artifact_publications SET witness_digest=?,phase='satisfied' WHERE task_id=? AND execution_id=?").run(witnesses, task, execution);
        });
        return;
      }
      if (pending.length < scope.roots.length) authority(() => {
        stage.assertSelectedSourceCurrent(pending.map(file => file.path));
        stage = WorkspaceStage.createFiles(this.stateRoot, this.workspace, pending.map(file => file.path), row.binding, authority);
        this.kernel.db.sql.query("UPDATE topology_artifact_publications SET stage_path=?,reference=? WHERE task_id=? AND execution_id=?")
          .run(stage.path, canonical(stage.reference()), task, execution);
      });
    }
    const selected = files.filter(file => stage.fileScope().roots.includes(join(this.workspace, file.path)));
    const skipped = files.filter(file => !selected.includes(file));
    const originalAuthority = authority;
    authority = operation => originalAuthority(() => { requireThat(skipped.every(matches), "topology_publication_content_changed"); return operation(); });
    authority(() => {
      this.kernel.db.sql.query("UPDATE topology_artifact_publications SET witness_digest=?,phase=CASE WHEN phase='baseline' THEN 'staged' ELSE phase END WHERE task_id=? AND execution_id=?")
        .run(witnesses, task, execution);
    });
    if (stage.publicationState().phase === "prepared") {
      for (const file of selected) {
        const bytes = authority(() => file.load());
        stage.writeSelectedFile(authority, file.path, bytes);
      }
      stage.seal(authority);
    }
    const proposal = stage.proposalReceipt();
    requireThat(row.proposal_digest === null || row.proposal_digest === proposal.proposal_digest, "topology_publication_proposal_changed");
    requireThat(proposal.changed_paths.every(path => selected.some(file => file.path === path)), "topology_publication_path_changed");
    const snapshots = snapshotReads(stage.fileScope().tree, selected.map(file => join(stage.fileScope().tree, file.path)));
    requireThat(selected.every(file => snapshots.some(snapshot => snapshot.path === join(stage.fileScope().tree, file.path)
      && snapshot.sha256 === file.sha256)), "topology_publication_content_changed");
    authority(() => { this.kernel.db.sql.query("UPDATE topology_artifact_publications SET proposal_digest=? WHERE task_id=? AND execution_id=?")
      .run(proposal.proposal_digest, task, execution); });
    stage.promote(authority, proposal.proposal_digest);
    authority(() => {
      stage.assertApplied(proposal.proposal_digest);
      if (row.phase !== "applied") {
        const snapshot = this.kernel.inspect(actor, task);
        this.kernel.db.sql.query("INSERT INTO events(task_id,kind,revision,fence,principal,origin,at,payload) VALUES (?,'topology.artifacts_published',?,?,?,'schedule',?,?)")
          .run(task, snapshot.revision, snapshot.fence, actor.id, this.kernel.db.now(), canonical({ execution_id: execution,
            proposal_digest: proposal.proposal_digest, files: files.map(({ path, sha256 }) => ({ path, sha256 })) }));
        this.kernel.db.sql.query("UPDATE topology_artifact_publications SET phase='applied' WHERE task_id=? AND execution_id=?").run(task, execution);
      }
    });
  }
}
