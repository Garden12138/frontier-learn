import re
from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.api.jobs import JobResponse

Mode = Literal["INTUITIVE", "DEEP", "PRACTICE"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PageBlock(StrictModel):
    id: str = Field(pattern=r"^b\d{1,2}$")
    heading: str = Field(max_length=200)
    text: str = Field(min_length=1, max_length=2000)
    selector: str = Field(max_length=500)


class Selection(StrictModel):
    block_id: str = Field(pattern=r"^b\d{1,2}$")
    quote: str = Field(min_length=3, max_length=1000)


class PageSnapshot(StrictModel):
    url: str = Field(max_length=2048)
    title: str = Field(min_length=1, max_length=500)
    provider: Literal["ARXIV", "HUGGINGFACE", "MANUAL"]
    scope: Literal["ABSTRACT", "BODY", "MANUAL"]
    blocks: list[PageBlock] = Field(min_length=1, max_length=40)
    selection: Selection | None = None
    truncated: bool = False

    @model_validator(mode="after")
    def boundaries(self) -> "PageSnapshot":
        size = sum(len(block.text) for block in self.blocks)
        if not 40 <= size <= 30000 or len({b.id for b in self.blocks}) != len(self.blocks):
            raise ValueError("Invalid page size or duplicate block IDs")
        if self.provider == "MANUAL":
            if self.url or self.scope != "MANUAL" or any(b.selector for b in self.blocks):
                raise ValueError("Manual sources have no verified web locator")
        else:
            url = urlsplit(self.url)
            if (
                url.scheme != "https"
                or url.username
                or url.password
                or url.port
                or url.query
                or url.fragment
                or re.search(r"[\s\\]", self.url)
            ):
                raise ValueError("Invalid source URL")
            if self.provider == "ARXIV":
                match = re.fullmatch(
                    r"/(abs|html)/((?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})"
                    r"(?:v\d+)?)/?",
                    url.path,
                )
                if url.hostname != "arxiv.org" or not match:
                    raise ValueError("Unsupported arXiv URL")
                if self.scope != ("ABSTRACT" if match[1] == "abs" else "BODY"):
                    raise ValueError("Incorrect extraction scope")
            else:
                parts = url.path.strip("/").split("/")
                reserved = {
                    "models",
                    "datasets",
                    "spaces",
                    "docs",
                    "organizations",
                    "orgs",
                    "collections",
                    "blog",
                    "papers",
                    "tasks",
                    "settings",
                    "login",
                    "join",
                    "api",
                }
                if (
                    url.hostname != "huggingface.co"
                    or not 1 <= len(parts) <= 2
                    or parts[0] in reserved
                    or any(not re.fullmatch(r"[\w.-]+", p, re.ASCII) for p in parts)
                    or self.scope != "BODY"
                ):
                    raise ValueError("Unsupported model page")
        if self.selection and not any(
            b.id == self.selection.block_id and self.selection.quote in b.text for b in self.blocks
        ):
            raise ValueError("Selection must match the supplied snapshot")
        return self


class AnalyzePageRequest(StrictModel):
    cloud_processing_allowed: bool = False
    page: PageSnapshot
    goal_id: UUID | None = None
    task_id: UUID | None = None
    mode: Mode = "INTUITIVE"
    consent: Literal[True]


class AskRequest(StrictModel):
    cloud_processing_allowed: bool = False
    expected_version: int = Field(ge=1)
    question: str = Field(min_length=1, max_length=1000)
    mode: Mode = "INTUITIVE"
    selection: Selection | None = None


class Citation(StrictModel):
    block_id: str = Field(max_length=20)
    quote: str = Field(min_length=1, max_length=1000)
    status: Literal["SNAPSHOT_MATCH", "UNVERIFIED"] = "UNVERIFIED"
    selector: str = Field(default="", max_length=500)


class Guide(StrictModel):
    label: Literal["LOCAL_RULES", "MODEL_EXPLANATION"]
    summary: str = Field(min_length=1, max_length=1200)
    points: list[str] = Field(min_length=1, max_length=3)
    prerequisites: list[str] = Field(max_length=3)
    steps: list[str] = Field(min_length=1, max_length=3)
    citations: list[Citation] = Field(max_length=3)

    @model_validator(mode="after")
    def bounded_items(self) -> "Guide":
        if any(
            not value or len(value) > 700
            for value in [*self.points, *self.steps, *self.prerequisites]
        ):
            raise ValueError("Invalid guide item")
        return self


class TurnResponse(BaseModel):
    id: UUID
    question: str
    mode: Mode
    job: JobResponse
    guide: Guide | None
    created_at: datetime


class SessionSummary(BaseModel):
    id: UUID
    title: str
    url: str
    scope: str
    version: int
    goal_id: UUID | None
    task_id: UUID | None
    created_at: datetime


class SessionResponse(SessionSummary):
    page: PageSnapshot
    turns: list[TurnResponse]
