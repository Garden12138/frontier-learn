from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from app.core.errors import Problem

Output = TypeVar("Output", bound=BaseModel)


class ModelContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    user_goal: str = Field(default="", max_length=500)
    # Only selected excerpts; raw documents, tokens and tool permissions have no field here.
    evidence_snippets: list[str] = Field(default_factory=list, max_length=3)
    untrusted_text: str = Field(default="", max_length=4000)
    cloud_processing_allowed: bool = False

    def bounded_text(self) -> str:
        if any(len(snippet) > 1000 for snippet in self.evidence_snippets):
            raise Problem(400, "CONTEXT_LIMIT", "请缩小需要处理的内容范围。")
        return "\n".join([self.user_goal, *self.evidence_snippets, self.untrusted_text])


@dataclass(frozen=True)
class Generated[Output: BaseModel]:
    output: Output
    input_units: int
    output_units: int
    provider: str
    input_tokens: int | None = None
    output_tokens: int | None = None


class LLMProvider(Protocol):
    name: str
    is_cloud: bool

    async def generate_structured(
        self, operation: str, context: ModelContext, schema: type[Output], *, max_output_units: int
    ) -> Generated[Output]: ...

    def stream_tutor(
        self, context: ModelContext, *, max_output_units: int
    ) -> AsyncIterator[str]: ...


def check_model_access(provider: LLMProvider, context: ModelContext) -> None:
    context.bounded_text()
    if provider.is_cloud and not context.cloud_processing_allowed:
        raise Problem(403, "MODEL_CONSENT_REQUIRED", "使用外部模型前请先确认内容处理授权。")
