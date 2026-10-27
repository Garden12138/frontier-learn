from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ArtifactCreate(StrictModel):
    assessment_id: UUID


class ArtifactEdit(StrictModel):
    version: int = Field(ge=1)
    markdown: str = Field(min_length=1, max_length=50000)

    @field_validator("markdown")
    @classmethod
    def bounded_markdown(cls, value: str) -> str:
        if len(value.encode()) > 50000:
            raise ValueError("Markdown exceeds 50KB")
        return value


class PreviewRequest(StrictModel):
    version: int = Field(ge=1)
    source_id: UUID
    path: str = Field(min_length=4, max_length=200)
    mode: Literal["NEW", "MANUAL_MERGE"] = "NEW"


class WritePreview(StrictModel):
    source_id: UUID
    source_version: int
    repository: str
    path: str
    mode: Literal["NEW", "MANUAL_MERGE"]
    base_branch: str
    base_sha: str
    file_sha: str | None
    branch: str
    diff: str
    content_hash: str


class ArtifactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    assessment_id: UUID
    title: str
    markdown: str
    version: int
    preview: WritePreview | None
    job_id: UUID | None
    pr_number: int | None
    pr_url: str | None
    merged_at: datetime | None
    reindexed_at: datetime | None
    created_at: datetime


class WriteApproval(StrictModel):
    version: int = Field(ge=1)
    confirm: Literal[True]


class WritePermission(StrictModel):
    version: int = Field(ge=1)
    confirm: Literal[True]
    # Provisioned through the API, never returned or inserted into a page or model context.
    credential: SecretStr = Field(min_length=1, max_length=4000)
    path_prefixes: list[str] = Field(min_length=1, max_length=5)
