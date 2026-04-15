"""CLI layer: provider abstraction, process tracking, streaming."""

from controlmesh.cli.auth import AuthResult as AuthResult
from controlmesh.cli.auth import AuthStatus as AuthStatus
from controlmesh.cli.auth import check_all_auth as check_all_auth
from controlmesh.cli.base import BaseCLI as BaseCLI
from controlmesh.cli.base import CLIConfig as CLIConfig
from controlmesh.cli.coalescer import CoalesceConfig as CoalesceConfig
from controlmesh.cli.coalescer import StreamCoalescer as StreamCoalescer
from controlmesh.cli.factory import create_cli as create_cli
from controlmesh.cli.process_registry import ProcessRegistry as ProcessRegistry
from controlmesh.cli.service import CLIService as CLIService
from controlmesh.cli.service import CLIServiceConfig as CLIServiceConfig
from controlmesh.cli.types import AgentRequest as AgentRequest
from controlmesh.cli.types import AgentResponse as AgentResponse
from controlmesh.cli.types import CLIResponse as CLIResponse

__all__ = [
    "AgentRequest",
    "AgentResponse",
    "AuthResult",
    "AuthStatus",
    "BaseCLI",
    "CLIConfig",
    "CLIResponse",
    "CLIService",
    "CLIServiceConfig",
    "CoalesceConfig",
    "ProcessRegistry",
    "StreamCoalescer",
    "check_all_auth",
    "create_cli",
]
