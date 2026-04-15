# Confirmed Facts
- packet/task read surfaces already existed, but task-bounded selection was still exposed to packet-name ordering accidents
- review handoff packet behavior was under-tested before this pack
- operator-facing read surfaces need one consistent latest-first episode order so packet ids, primary identity, and source refs do not drift apart
- the operator read surface can remain narrow by composing execution evidence reads and replay-backed handoff packets only

# Risks
- future operator tooling can still sprawl into dashboard or broad query work if this pack is used as a wedge
- future replay/query changes can reintroduce identity drift if task ordering and handoff primary identity are not kept on the same rule

# Deferred
- richer operator APIs
- dashboard/UI
- broad query/index storage
- any read-triggered recovery or promotion workflow

# Decision Records
- 2026-04-15: Close `Operator Read Surface Pack` as a separate post-promotion read-only package rather than reopening execution-read-surface or replay/query block docs.
