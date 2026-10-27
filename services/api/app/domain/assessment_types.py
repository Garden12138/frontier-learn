from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AssessmentCreate(StrictModel):
    session_id: UUID


class AssessmentAnswer(StrictModel):
    version: int = Field(ge=1)
    choice: Literal["A", "B", "C"]


class ConfirmEvidence(StrictModel):
    version: int = Field(ge=1)
    confirm: Literal[True]


class AssessmentQuestion(StrictModel):
    prompt: str
    excerpt: str
    block_id: str
    options: dict[str, str]
    rubric: list[str]
    scope: Literal["SOURCE_COMPREHENSION"] = "SOURCE_COMPREHENSION"


class AssessmentFeedback(StrictModel):
    result: Literal["SUPPORTED", "NEEDS_REVIEW"]
    basis: str
    uncertainty: str
    method: Literal["LOCAL_RULES"] = "LOCAL_RULES"
    answered_at: datetime | None = None


class AssessmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    session_id: UUID
    concept_name: str
    question: AssessmentQuestion
    answer: str | None
    feedback: AssessmentFeedback | None
    version: int
    confirmed_at: datetime | None
    evidence_id: UUID | None
    plan_revision: int | None
    created_at: datetime
