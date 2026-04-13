# Current Goal
Introduce a dedicated runtime event substrate that stays separate from frontstage history.

# Current Status
stopline

# Frozen Boundaries
- do not add a runtime UI or event browser in this cut
- do not write runtime events into transcript storage
- do not redesign command surfaces beyond what the substrate contract needs
- do not broaden into analytics, replay, or alerting

# Ready Queue
1. No auto-dispatch remains in the current autonomous round

# Non-goals
- runtime event panel
- attachment/event replay
- aggregate analytics
- broader observability redesign

# Completion Condition
- dedicated runtime event storage contract exists
- runtime event storage implementation exists under a dedicated runtime root
- at least one real runtime producer seam writes lifecycle events into the dedicated runtime root
- runtime events remain separate from transcript truth
- focused verification passes
- checkpoint note can be written
