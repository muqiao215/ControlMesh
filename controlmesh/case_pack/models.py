from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class EvidenceBackedModel(BaseModel):
    evidence_refs: list[str] = Field(default_factory=list)


class Message(EvidenceBackedModel):
    id: str
    author: str
    role: str
    ts: str
    summary: str


class Link(BaseModel):
    id: str
    label: str
    url: str
    summary: str | None = None


class Artifact(EvidenceBackedModel):
    id: str
    label: str
    kind: str
    locator: str
    summary: str | None = None


class Event(EvidenceBackedModel):
    id: str
    title: str
    summary: str


class ToolEvent(EvidenceBackedModel):
    id: str
    tool: str
    action: str
    summary: str
    kept: bool = False
    linked_event_ids: list[str] = Field(default_factory=list)
    why_it_matters: str | None = None


class TimelineEntry(EvidenceBackedModel):
    id: str
    order: int
    kind: Literal["event", "tool_event"]
    ref_id: str
    title: str
    summary: str


class TurningPoint(EvidenceBackedModel):
    id: str
    title: str
    summary: str
    event_ids: list[str] = Field(default_factory=list)
    tool_event_ids: list[str] = Field(default_factory=list)


class LiftedItem(EvidenceBackedModel):
    id: str
    title: str
    summary: str
    timeline_refs: list[str] = Field(default_factory=list)
    turning_point_refs: list[str] = Field(default_factory=list)


class LiftedView(BaseModel):
    questions: list[LiftedItem] = Field(default_factory=list)
    misconceptions: list[LiftedItem] = Field(default_factory=list)
    resolutions: list[LiftedItem] = Field(default_factory=list)


class CasePack(BaseModel):
    case_id: str
    title: str
    summary: str
    messages: list[Message] = Field(default_factory=list)
    links: list[Link] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list)
    tool_events: list[ToolEvent] = Field(default_factory=list)
    timeline: list[TimelineEntry] = Field(default_factory=list)
    turning_points: list[TurningPoint] = Field(default_factory=list)
    lifted_view: LiftedView = Field(default_factory=LiftedView)
