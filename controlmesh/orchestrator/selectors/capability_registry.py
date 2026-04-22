"""Conservative worker/channel capability registry.

Provider labels in ControlMesh are execution channels, not hard guarantees about
the underlying backend model. This registry lets routing code reason about
channel capabilities separately from provider/model resolution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping


class Capability(StrEnum):
    """Internal capability labels for conservative routing decisions."""

    CODE_EDIT = "code_edit"
    REPO_REVIEW = "repo_review"
    BASIC_SUMMARIZE = "basic_summarize"
    POLISH = "polish"
    RESEARCH = "research"
    BROWSER = "browser"
    FEISHU_NATIVE = "feishu_native"
    LONG_TASK = "long_task"


class CapabilityConfidence(IntEnum):
    """Conservative confidence that a channel can handle a capability well."""

    NONE = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3


@dataclass(frozen=True, slots=True)
class CapabilityProfile:
    """Capability profile for one internal worker/channel identity."""

    profile_id: str
    display_name: str
    notes: str
    confidences: Mapping[Capability, CapabilityConfidence] = field(
        default_factory=lambda: MappingProxyType({})
    )


@dataclass(frozen=True, slots=True)
class CapabilitySummary:
    """User-neutral summary returned by the query API."""

    channel: str
    profile_id: str
    display_name: str
    notes: str
    confidences: Mapping[Capability, CapabilityConfidence]


_EMPTY_PROFILE = CapabilityProfile(
    profile_id="unknown",
    display_name="Unknown channel",
    notes="No conservative capability metadata is registered for this channel.",
)


class CapabilityRegistry:
    """Readonly lookup for channel capability profiles."""

    def __init__(
        self,
        *,
        profiles: Mapping[str, CapabilityProfile] | None = None,
        aliases: Mapping[str, str] | None = None,
        channels: tuple[str, ...] = (),
    ) -> None:
        self._profiles = dict(profiles or {})
        self._aliases = dict(aliases or {})
        self._channels = channels

    def summary_for(self, channel: str) -> CapabilitySummary:
        """Return the conservative summary for a provider/channel label."""
        normalized = channel.strip().lower()
        profile = self._profile_for(normalized)
        return CapabilitySummary(
            channel=normalized or "unknown",
            profile_id=profile.profile_id,
            display_name=profile.display_name,
            notes=profile.notes,
            confidences=profile.confidences,
        )

    def confidence_for(
        self,
        channel: str,
        capability: Capability | str,
    ) -> CapabilityConfidence:
        """Return the conservative confidence for one capability query."""
        cap = capability if isinstance(capability, Capability) else Capability(capability)
        profile = self._profile_for(channel.strip().lower())
        return profile.confidences.get(cap, CapabilityConfidence.NONE)

    def preferred_channels_for(
        self,
        capability: Capability | str,
        *,
        minimum: CapabilityConfidence = CapabilityConfidence.LOW,
    ) -> tuple[str, ...]:
        """Return known default channels ordered by confidence for a capability."""
        cap = capability if isinstance(capability, Capability) else Capability(capability)
        ranked = sorted(
            (
                (channel, self.confidence_for(channel, cap))
                for channel in self._channels
            ),
            key=lambda item: (-int(item[1]), item[0]),
        )
        return tuple(alias for alias, confidence in ranked if confidence >= minimum)

    def _profile_for(self, channel: str) -> CapabilityProfile:
        profile_id = self._aliases.get(channel, channel)
        return self._profiles.get(profile_id, _EMPTY_PROFILE)


def default_capability_registry() -> CapabilityRegistry:
    """Return the built-in conservative capability registry."""
    profiles = {
        "claude_channel": CapabilityProfile(
            profile_id="claude_channel",
            display_name="Claude-compatible channel",
            notes=(
                "Treat the claude path as a lightweight/basic channel by default. "
                "The actual backend may be Anthropic Claude, GLM 5.1, MiniMax 2.7, "
                "or another Claude-compatible endpoint."
            ),
            confidences=MappingProxyType(
                {
                    Capability.BASIC_SUMMARIZE: CapabilityConfidence.MEDIUM,
                    Capability.POLISH: CapabilityConfidence.MEDIUM,
                    Capability.RESEARCH: CapabilityConfidence.LOW,
                    Capability.CODE_EDIT: CapabilityConfidence.LOW,
                    Capability.REPO_REVIEW: CapabilityConfidence.LOW,
                }
            ),
        ),
        "codex": CapabilityProfile(
            profile_id="codex",
            display_name="Codex",
            notes="Prefer for shell-grounded code edits, repo review, and verification.",
            confidences=MappingProxyType(
                {
                    Capability.CODE_EDIT: CapabilityConfidence.HIGH,
                    Capability.REPO_REVIEW: CapabilityConfidence.HIGH,
                    Capability.BASIC_SUMMARIZE: CapabilityConfidence.MEDIUM,
                    Capability.POLISH: CapabilityConfidence.LOW,
                    Capability.RESEARCH: CapabilityConfidence.LOW,
                    Capability.LONG_TASK: CapabilityConfidence.LOW,
                }
            ),
        ),
        "gemini": CapabilityProfile(
            profile_id="gemini",
            display_name="Gemini",
            notes="Use conservatively for research and multimodal/browser-adjacent work.",
            confidences=MappingProxyType(
                {
                    Capability.BASIC_SUMMARIZE: CapabilityConfidence.MEDIUM,
                    Capability.POLISH: CapabilityConfidence.MEDIUM,
                    Capability.RESEARCH: CapabilityConfidence.MEDIUM,
                    Capability.BROWSER: CapabilityConfidence.LOW,
                    Capability.CODE_EDIT: CapabilityConfidence.LOW,
                    Capability.REPO_REVIEW: CapabilityConfidence.LOW,
                }
            ),
        ),
        "openai_agents": CapabilityProfile(
            profile_id="openai_agents",
            display_name="OpenAI Agents backend",
            notes=(
                "This is an orchestration backend, not a transport owner or capability "
                "guarantee for direct repo mutation."
            ),
            confidences=MappingProxyType(
                {
                    Capability.BASIC_SUMMARIZE: CapabilityConfidence.MEDIUM,
                    Capability.POLISH: CapabilityConfidence.MEDIUM,
                    Capability.RESEARCH: CapabilityConfidence.MEDIUM,
                    Capability.CODE_EDIT: CapabilityConfidence.LOW,
                    Capability.REPO_REVIEW: CapabilityConfidence.LOW,
                    Capability.LONG_TASK: CapabilityConfidence.LOW,
                }
            ),
        ),
        "claw": CapabilityProfile(
            profile_id="claw",
            display_name="Claw runtime",
            notes=(
                "Treat claw as an external coding runtime channel. "
                "Prefer conservative routing until its JSON/session contract is hardened."
            ),
            confidences=MappingProxyType(
                {
                    Capability.BASIC_SUMMARIZE: CapabilityConfidence.MEDIUM,
                    Capability.CODE_EDIT: CapabilityConfidence.LOW,
                    Capability.REPO_REVIEW: CapabilityConfidence.LOW,
                    Capability.POLISH: CapabilityConfidence.LOW,
                    Capability.RESEARCH: CapabilityConfidence.LOW,
                }
            ),
        ),
        "opencode": CapabilityProfile(
            profile_id="opencode",
            display_name="OpenCode runtime",
            notes=(
                "Treat opencode as an external runtime channel with its own provider/model routing."
            ),
            confidences=MappingProxyType(
                {
                    Capability.BASIC_SUMMARIZE: CapabilityConfidence.MEDIUM,
                    Capability.CODE_EDIT: CapabilityConfidence.LOW,
                    Capability.REPO_REVIEW: CapabilityConfidence.LOW,
                    Capability.POLISH: CapabilityConfidence.LOW,
                    Capability.RESEARCH: CapabilityConfidence.LOW,
                }
            ),
        ),
        "taskhub": CapabilityProfile(
            profile_id="taskhub",
            display_name="TaskHub",
            notes="Use only for background and long-running work coordination.",
            confidences=MappingProxyType(
                {
                    Capability.LONG_TASK: CapabilityConfidence.HIGH,
                }
            ),
        ),
        "feishu_native": CapabilityProfile(
            profile_id="feishu_native",
            display_name="Feishu native tools",
            notes="Use only for Feishu-native auth, identity, and platform operations.",
            confidences=MappingProxyType(
                {
                    Capability.FEISHU_NATIVE: CapabilityConfidence.HIGH,
                }
            ),
        ),
    }
    aliases = {
        "claude": "claude_channel",
        "claude_channel": "claude_channel",
        "codex": "codex",
        "gemini": "gemini",
        "openai_agents": "openai_agents",
        "claw": "claw",
        "opencode": "opencode",
        "taskhub": "taskhub",
        "feishu_native": "feishu_native",
    }
    return CapabilityRegistry(
        profiles=profiles,
        aliases=aliases,
        channels=(
            "claude",
            "codex",
            "gemini",
            "claw",
            "opencode",
            "openai_agents",
            "taskhub",
            "feishu_native",
        ),
    )
