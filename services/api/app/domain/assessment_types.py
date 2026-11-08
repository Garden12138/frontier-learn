import re
import unicodedata
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.api.jobs import JobResponse
from app.domain.tutoring_types import Selection


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AssessmentCreate(StrictModel):
    session_id: UUID
    kind: Literal["SOURCE_COMPREHENSION", "CONCEPT_CHECK"] = "SOURCE_COMPREHENSION"
    cloud_processing_allowed: bool = False
    block_id: str | None = Field(default=None, pattern=r"^b\d{1,2}$")
    selection: Selection | None = None


class AssessmentRegenerate(StrictModel):
    version: int = Field(ge=1)
    cloud_processing_allowed: Literal[True]


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
    source_excerpt: str = Field(default="", max_length=1800)
    source_reason: str = "旧版材料范围"
    quality_notice: str = "结构筛查与引文匹配不能证明选项语义正确；请人工复查题目、各选项与原文。"
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
        values = [
            "".join(c for c in unicodedata.normalize("NFKC", value).casefold() if c.isalnum())
            for value in self.options.model_dump().values()
        ]
        if (
            not all(values)
            or len(set(values)) != 3
            or any(not 3 <= len(item.strip()) <= 300 for item in self.rubric)
        ):
            raise ValueError("Question options and rubric must be distinct and bounded")
        if any(
            re.search(
                r"all of the above|none of the above|以上[皆都全]|上述[皆都全]|选项\s*[ABC]",
                value,
                re.I,
            )
            for value in self.options.model_dump().values()
        ):
            raise ValueError("Self-referential or combined options are not supported")
        return self


def option_quality_notice(options: ChoiceOptions) -> str:
    values = [
        "".join(c for c in unicodedata.normalize("NFKC", value).casefold() if c.isalnum())
        for value in options.model_dump().values()
    ]
    contradictory = any(
        ("不" in value and value.replace("不", "", 1) in values)
        or ("doesnot" in value and value.replace("doesnot", "", 1) in values)
        for value in values
        if "不" in value or "doesnot" in value
    )
    return ("检测到直接否定的相对选项，请特别复查是否有歧义或矛盾。" if contradictory else "") + (
        "已做结构与重复选项筛查；引用匹配只证明文字存在，模型答案未经独立语义验证。"
        "请人工复查题干、各选项与引文，尤其检查多个正确答案或矛盾。"
    )
