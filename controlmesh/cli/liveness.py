"""Liveness policies for provider subprocess supervision."""

from __future__ import annotations

from dataclasses import dataclass

from controlmesh.cli.timeout_controller import TimeoutConfig, TimeoutController


@dataclass(frozen=True, slots=True)
class RunLivenessPolicy:
    """Timeout and status cadence for one provider run."""

    startup_timeout_s: float = 10
    first_event_timeout_s: float = 60
    idle_warning_s: float = 60
    idle_soft_timeout_s: float = 300
    hard_timeout_s: float = 1800
    status_interval_s: float = 60
    kill_on_idle: bool = True


FOREGROUND_POLICY = RunLivenessPolicy(
    first_event_timeout_s=60,
    idle_warning_s=60,
    idle_soft_timeout_s=300,
    hard_timeout_s=1800,
    status_interval_s=60,
    kill_on_idle=True,
)

BACKGROUND_POLICY = RunLivenessPolicy(
    first_event_timeout_s=90,
    idle_warning_s=120,
    idle_soft_timeout_s=1800,
    hard_timeout_s=7200,
    status_interval_s=300,
    kill_on_idle=False,
)


def timeout_controller_for_policy(
    policy: RunLivenessPolicy,
    *,
    mode: str,
    chat_id: int,
    turn_id: str,
    max_runtime_seconds: float | None = None,
) -> TimeoutController:
    """Build a TimeoutController from a liveness policy."""
    max_runtime = max_runtime_seconds or policy.hard_timeout_s
    idle_timeout = policy.idle_soft_timeout_s if policy.kill_on_idle else None
    controller = TimeoutController(
        TimeoutConfig(
            timeout_seconds=policy.idle_soft_timeout_s if policy.kill_on_idle else max_runtime,
            idle_timeout_seconds=idle_timeout,
            max_runtime_seconds=max_runtime,
            mode=mode,
            warning_intervals=[],
            extend_on_activity=False,
            activity_extension=0.0,
            max_extensions=0,
        ),
    )
    controller.attach_process(pid=None, chat_id=chat_id, turn_id=turn_id, mode=mode)
    return controller
