"""CLI backend factory -- returns the right provider based on config."""

from __future__ import annotations

import logging

from controlmesh.cli.base import BaseCLI, CLIConfig

logger = logging.getLogger(__name__)


def create_cli(config: CLIConfig) -> BaseCLI:
    """Create a CLI backend instance based on ``config.provider``."""
    logger.debug("CLI factory creating provider=%s", config.provider)
    if config.provider == "gemini":
        from controlmesh.cli.gemini_provider import GeminiCLI

        return GeminiCLI(config)

    if config.provider == "codex":
        from controlmesh.cli.codex_provider import CodexCLI

        return CodexCLI(config)

    if config.provider == "claw":
        from controlmesh.cli.claw_provider import ClawCLI

        return ClawCLI(config)

    if config.provider == "opencode":
        from controlmesh.cli.opencode_provider import OpenCodeCLI

        return OpenCodeCLI(config)

    if config.provider == "openai_agents":
        from controlmesh.cli.openai_agents_provider import OpenAIAgentsCLI

        return OpenAIAgentsCLI(config)

    from controlmesh.cli.claude_provider import ClaudeCodeCLI

    return ClaudeCodeCLI(config)
