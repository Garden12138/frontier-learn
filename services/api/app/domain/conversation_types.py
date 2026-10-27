from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.api.jobs import JobResponse
from app.domain.planning_types import StrictModel
from app.ingestion.safe_fetch import share_url


class ConversationPart(StrictModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
    kind: Literal["TEXT", "CODE"]
    text: str = Field(min_length=1, max_length=4000)


class ConversationMessage(StrictModel):
    id: str = Field(pattern=r"^m\d{1,2}$")
    role: Literal["USER", "ASSISTANT", "UNKNOWN"]
    parts: list[ConversationPart] = Field(min_length=1, max_length=30)


class ConversationDocument(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    messages: list[ConversationMessage] = Field(min_length=1, max_length=40)
    warnings: list[str] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def bounded(self) -> "ConversationDocument":
        total = sum(len(p.text) for m in self.messages for p in m.parts)
        if not 20 <= total <= 30000 or len({m.id for m in self.messages}) != len(self.messages):
            raise ValueError("Conversation exceeds bounds or has duplicate IDs")
        return self


class ImportConversationRequest(StrictModel):
    url: str | None = Field(default=None, max_length=2048)
    pasted_text: str | None = Field(default=None, min_length=20, max_length=30000)
    consent: Literal[True]

    @field_validator("url")
    @classmethod
    def supported_url(cls, value: str | None) -> str | None:
        return share_url(value) if value is not None else None

    @model_validator(mode="after")
    def one_source(self) -> "ImportConversationRequest":
        if (self.url is None) == (self.pasted_text is None):
            raise ValueError("Choose exactly one source")
        return self


class Candidate(StrictModel):
    id: UUID
    message_id: str
    part_index: int = Field(ge=0, le=29)
    quote: str = Field(min_length=1, max_length=180)
    question: str = Field(min_length=1, max_length=500)
    status: Literal["PROPOSED", "ADDED", "DISMISSED"] = "PROPOSED"
    concept_ids: list[UUID] = Field(default_factory=list, max_length=3)
    plan_id: UUID | None = None
    task_id: UUID | None = None


class RelatedKnowledge(BaseModel):
    concept_id: UUID
    name: str
    level: str
    confidence: str
    verified_at: datetime | None
    override_level: str | None


class CandidateResponse(Candidate):
    related: list[RelatedKnowledge]


class ConversationResponse(BaseModel):
    id: UUID
    source: Literal["SHARE", "PASTED"]
    url: str | None
    pasted_text: str | None
    version: int
    job: JobResponse
    document: ConversationDocument | None
    candidates: list[CandidateResponse]
    created_at: datetime


class ConversationSummary(BaseModel):
    id: UUID
    source: str
    title: str
    status: Literal["PENDING", "RUNNING", "PARTIAL", "SUCCEEDED", "FAILED", "CANCELLED"]
    created_at: datetime


class CandidateDecision(StrictModel):
    expected_version: int = Field(ge=1)
    action: Literal["ADD", "DISMISS"]
    plan_id: UUID | None = None
    expected_revision_no: int | None = Field(default=None, ge=1)
    estimated_minutes: int = Field(default=5, ge=5, le=240)

    @model_validator(mode="after")
    def destination(self) -> "CandidateDecision":
        if self.action == "ADD" and (self.plan_id is None or self.expected_revision_no is None):
            raise ValueError("Adding a task requires a current plan revision")
        if self.action == "DISMISS" and (
            self.plan_id is not None or self.expected_revision_no is not None
        ):
            raise ValueError("Dismiss does not modify a plan")
        return self
