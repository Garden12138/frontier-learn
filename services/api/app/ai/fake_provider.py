import json
from collections.abc import AsyncIterator

from pydantic import ValidationError

from app.ai.provider import Generated, ModelContext, Output, check_model_access
from app.core.errors import Problem


class FakeProvider:
    """Deterministic local simulation. No networking, tool calls or paid API keys."""

    name = "fake"
    is_cloud = False

    def __init__(self, responses: dict[str, dict[str, object]] | None = None) -> None:
        self.responses = responses or {}
        self.calls = 0

    async def generate_structured(
        self, operation: str, context: ModelContext, schema: type[Output], *, max_output_units: int
    ) -> Generated[Output]:
        check_model_access(self, context)
        if not 1 <= max_output_units <= 4096:
            raise Problem(400, "MODEL_BUDGET", "模型输出预算超出允许范围。")
        self.calls += 1
        response = self.responses.get(operation)
        if response is None:
            raise Problem(503, "FAKE_RESPONSE_MISSING", "本地模拟模型没有此操作的响应。")
        encoded = json.dumps(response, ensure_ascii=False)
        if len(encoded) > max_output_units:
            raise Problem(503, "MODEL_BUDGET", "模型响应超过本次预算，请缩小请求范围。")
        try:
            validated = schema.model_validate(response)
        except ValidationError:
            raise Problem(503, "MODEL_INVALID_OUTPUT", "模型响应不符合结构要求，请重试。") from None
        return Generated(validated, len(context.bounded_text()), len(encoded), self.name)

    async def stream_tutor(
        self, context: ModelContext, *, max_output_units: int
    ) -> AsyncIterator[str]:
        check_model_access(self, context)
        if not 1 <= max_output_units <= 4096:
            raise Problem(400, "MODEL_BUDGET", "模型输出预算超出允许范围。")
        self.calls += 1
        text = "模型解释/推测（本地模拟）：请先指出原文的一个主张，再用自己的例子解释并检查其限制。"
        if len(text) > max_output_units:
            raise Problem(503, "MODEL_BUDGET", "模型响应超过本次预算。")
        for offset in range(0, len(text), 12):
            yield text[offset : offset + 12]
