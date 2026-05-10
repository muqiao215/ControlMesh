"""Infrastructure: PID lock, restart sentinels, Docker management."""

from controlmesh.infra.docker import DockerManager
from controlmesh.infra.pidlock import acquire_lock, release_lock
from controlmesh.infra.restart import (
    EXIT_RESTART,
    consume_restart_marker,
    consume_restart_sentinel,
    request_restart,
    should_delegate_restart_to_service_manager,
    write_restart_marker,
    write_restart_sentinel,
)

__all__ = [
    "EXIT_RESTART",
    "DockerManager",
    "acquire_lock",
    "consume_restart_marker",
    "consume_restart_sentinel",
    "request_restart",
    "release_lock",
    "should_delegate_restart_to_service_manager",
    "write_restart_marker",
    "write_restart_sentinel",
]
