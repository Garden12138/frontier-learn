from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.api.jobs import JobResponse


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AssessmentCreate(StrictModel):
    session_id: UUID
    kind: Literal["SOURCE_COMPREHENSION", "CONCEPT_CHECK"] = "SOURCE_COMPREHENSION"
    cloud_processing_allowed: bool = False


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
    scope: Literal["SOURCE_COMPREHENSION", "CONCEPT_CHECK"] = "SOURCE_COMPREHENSION"


class AssessmentFeedback(StrictModel):
    result: Literal["SUPPORTED", "NEEDS_REVIEW"]
    basis: str
    uncertainty: str
    method: Literal["LOCAL_RULES", "MODEL_QUESTION_KEY"] = "LOCAL_RULES"
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
    job: JobResponse | None = None


class ChoiceOptions(StrictModel):
    A: str = Field(min_length=4, max_length=400)
    B: str = Field(min_length=4, max_length=400)
    C: str = Field(min_length=4, max_length=400)


class ConceptQuestion(StrictModel):
    prompt: str = Field(min_length=12, max_length=500)
    options: ChoiceOptions
    correct_choice: Literal["A", "B", "C"]
    rubric: list[str] = Field(min_length=1, max_length=3)
    basis: str = Field(min_length=12, max_length=1000)
    block_id: str = Field(min_length=1, max_length=40)
    quote: str = Field(min_length=12, max_length=600)

    @model_validator(mode="after")
    def distinct_options(self) -> "ConceptQuestion":
        values = [value.strip().casefold() for value in self.options.model_dump().values()]
        if len(set(values)) != 3 or any(not 3 <= len(item) <= 300 for item in self.rubric):
            raise ValueError("Question options and rubric must be distinct and bounded")
        return self
