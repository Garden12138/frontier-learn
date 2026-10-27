from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Level = Literal["UNKNOWN", "EXPOSED", "UNDERSTANDING", "APPLIED", "PROFICIENT"]
TaskStatus = Literal["PROPOSED", "ACCEPTED", "PAUSED", "SKIPPED", "COMPLETED"]
TaskKind = Literal[
    "EXPLORE", "CHECK", "READ", "APPLY", "REVIEW", "VERIFY", "REFLECT", "USER_INTEREST"
]


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", str_strip_whitespace=True, json_schema_serialization_defaults_required=True
    )


class PrerequisiteEdge(StrictModel):
    topic: str = Field(min_length=1, max_length=120)
    prerequisite: str = Field(min_length=1, max_length=120)


def topic_order(topics: list[str], edges: list[PrerequisiteEdge]) -> list[str]:
    if len({t.casefold() for t in topics}) != len(topics):
        raise ValueError("Duplicate topics")
    dependencies: dict[str, set[str]] = {topic: set() for topic in topics}
    for edge in edges:
        if edge.topic not in dependencies or edge.prerequisite not in dependencies:
            raise ValueError("Prerequisites must reference existing directions")
        dependencies[edge.topic].add(edge.prerequisite)
    result: list[str] = []
    while len(result) < len(topics):
        ready = next(
            (t for t in topics if t not in result and dependencies[t].issubset(result)), None
        )
        if ready is None:
            raise ValueError("Prerequisite cycle")
        result.append(ready)
    return result


class GoalInput(StrictModel):
    title: str = Field(min_length=1, max_length=500)
    minutes_per_day: int = Field(ge=5, le=240)
    priorities: list[str] = Field(default_factory=list, max_length=8)
    prerequisite_edges: list[PrerequisiteEdge] = Field(default_factory=list, max_length=16)
    self_report: Level = "UNKNOWN"
    self_report_reason: str = Field(default="", max_length=1000)
    timezone: str = Field(default="UTC", max_length=64)
    status: Literal["ACTIVE", "PAUSED"] = "ACTIVE"

    @field_validator("priorities")
    @classmethod
    def valid_priorities(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value]
        if any(not item or len(item) > 120 for item in cleaned):
            raise ValueError("Directions must contain 1–120 characters")
        return cleaned

    @field_validator("timezone")
    @classmethod
    def valid_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Unknown timezone") from None
        return value

    @model_validator(mode="after")
    def consistent_start(self) -> "GoalInput":
        topic_order(self.priorities or [self.title], self.prerequisite_edges)
        if self.self_report != "UNKNOWN" and len(self.self_report_reason) < 3:
            raise ValueError("Self-report requires a reason")
        return self


class GoalResponse(GoalInput):
    id: UUID
    version: int
    created_at: datetime
    updated_at: datetime


class GoalUpdate(GoalInput):
    version: int = Field(ge=1)


class ConversationTaskRef(StrictModel):
    import_id: UUID
    candidate_id: UUID


class PlanTask(StrictModel):
    id: UUID
    topic: str = Field(min_length=1, max_length=500)
    title: str = Field(min_length=1, max_length=700)
    instruction: str = Field(min_length=1, max_length=1400)
    why: str = Field(min_length=1, max_length=1400)
    kind: TaskKind
    stage: Literal["ORIENT", "READ", "VERIFY", "INTEREST"]
    estimated_minutes: int = Field(ge=5, le=240)
    status: TaskStatus = "PROPOSED"
    prerequisite_ids: list[UUID] = Field(default_factory=list, max_length=16)
    prerequisite_topics: list[str] = Field(default_factory=list, max_length=8)
    evidence_ids: list[UUID] = Field(default_factory=list, max_length=4)
    concept_ids: list[UUID] = Field(default_factory=list, max_length=4)
    material_url: str | None = Field(default=None, max_length=2048)
    origin: Literal["RULE", "USER"] = "RULE"
    completed_at: datetime | None = None
    conversation_ref: ConversationTaskRef | None = None

    @field_validator("material_url")
    @classmethod
    def valid_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            parsed = urlsplit(value)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.port not in (None, 443)
                or "\\" in value
                or any(ord(c) <= 32 for c in value)
            ):
                raise ValueError
        except ValueError:
            raise ValueError("Material links require HTTPS without embedded credentials") from None
        return value


class RouteTheme(StrictModel):
    topic: str
    why: str
    prerequisite_topics: list[str]
    estimated_minutes: int
    evidence_ids: list[UUID]


class PlanStage(StrictModel):
    title: str
    why: str
    task_ids: list[UUID]
    estimated_minutes: int


class PlanDocument(StrictModel):
    goal_snapshot: GoalResponse
    status: Literal["PROPOSED", "ACTIVE", "PAUSED"] = "PROPOSED"
    engine: Literal["LOCAL_RULES"] = "LOCAL_RULES"
    uncertainty: str
    roadmap: list[RouteTheme] = Field(min_length=1, max_length=8)
    stages: list[PlanStage] = Field(min_length=1, max_length=4)
    tasks: list[PlanTask] = Field(min_length=1, max_length=40)

    @model_validator(mode="after")
    def valid_dependencies(self) -> "PlanDocument":
        seen: set[UUID] = set()
        for task in self.tasks:
            if task.id in seen or not set(task.prerequisite_ids).issubset(seen):
                raise ValueError("Tasks must have unique IDs and valid earlier prerequisites")
            if task.estimated_minutes > self.goal_snapshot.minutes_per_day:
                raise ValueError("Split tasks that exceed daily time budget")
            seen.add(task.id)
        covered = [task_id for stage in self.stages for task_id in stage.task_ids]
        if len(covered) != len(set(covered)) or set(covered) != seen:
            raise ValueError("Stages must cover each task exactly once")
        return self


class GeneratePlanRequest(StrictModel):
    goal_id: UUID
    goal_version: int = Field(ge=1)
    expected_revision_no: int = Field(default=0, ge=0)


class InterestInput(StrictModel):
    title: str = Field(min_length=1, max_length=500)
    estimated_minutes: int = Field(ge=5, le=240)
    material_url: str | None = Field(default=None, max_length=2048)

    @field_validator("material_url")
    @classmethod
    def valid_url(cls, value: str | None) -> str | None:
        return PlanTask.valid_url(value)


class PlanAction(StrictModel):
    revision_no: int = Field(ge=1)
    action: Literal["ACCEPT", "PAUSE", "RESUME", "SKIP", "REORDER", "INSERT", "COMPLETE", "RESTORE"]
    task_id: UUID | None = None
    ordered_task_ids: list[UUID] | None = Field(default=None, max_length=40)
    interest: InterestInput | None = None
    restore_revision_no: int | None = Field(default=None, ge=1)


class SourceReference(StrictModel):
    evidence_id: UUID
    available: bool
    kind: str | None = None
    observed_at: datetime | None = None
    url: str | None = None
    label: str


class PlanResponse(PlanDocument):
    id: UUID
    revision_no: int
    rationale: str
    created_at: datetime
    goal_changed: bool
    today_task_ids: list[UUID]
    today_completed_minutes: int
    today_remaining_minutes: int
    sources: list[SourceReference]
