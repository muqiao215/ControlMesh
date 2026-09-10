## Current
Root implementation and local acceptance complete; native OpenCode release review next.
## Done
- Opt-in per-process native error monitoring stops explicit OpenCode quota retries before timeout, using existing process-tree cleanup.
- Added error_code=quota_exhausted and provider-reported quota_reset_at across CLI/stream/agent responses. Session identity retained; no automatic provider switching or scheduling based on timezone-free timestamps.
- Real native ZAI quota probe returned in 3.61 seconds, timed_out=false, with explicit recovery time. No credential or raw error payload published.
- 724 CLI, execution-grant and golden tests passed in 13.56 seconds. Changed CLI Ruff and six-module focused mypy passed. Real child fixtures cover split writes and ordinary 429 non-abort; model text cannot trigger detection.
## Remaining
Subagent review, full CI, merge and official release/PyPI visibility verification. Installed service upgrade is separate.
## Issues
Initial strict mypy surfaced existing parser narrowing and process-wait test-double typing; corrected without behavior changes. Detection depends on the verified native stream-error format exposed by --print-logs; unknown errors retain ordinary failure/timeout behavior.
## Next
Native OpenCode reviewer publishes next patch release through repository gates and returns exact PR, merge, tag, package and release evidence.
