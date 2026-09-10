# OpenCode quota detection
Goal: classify explicit provider quota exhaustion during a live OpenCode run, stop native retry promptly and preserve recovery information. Root implements/verifies; a native OpenCode worker reviews and publishes through normal CI/release gates.
Acceptance: real quota log stops child before timeout; reset text preserved without invented timezone; ordinary 429, model prose, tool output and unrelated historical logs cannot trigger; structured error reaches agent response; session preserved; other providers unchanged.
Phases: implementation complete; regression/live verification complete; delegated release pending.
Next: implement per-process stderr observation and strict quota classification.
