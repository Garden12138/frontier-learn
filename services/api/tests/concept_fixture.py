"""Deterministic browser-only Fake. Never used by production code."""

import asyncio
import json

from app.ai.fake_provider import FakeProvider
from app.ai.provider import Generated, ModelContext, Output
from app.core.errors import Problem


class BrowserConceptProvider(FakeProvider):
    def __init__(self) -> None:
        super().__init__({})
        self.failed: set[str] = set()

    async def generate_structured(
        self, operation: str, context: ModelContext, schema: type[Output], *, max_output_units: int
    ) -> Generated[Output]:
        source = json.loads(context.untrusted_text)
        text = source["source_excerpt"]
        await asyncio.sleep(0.8)
        if "TRIAL_FAIL_ONCE" in text and text not in self.failed:
            self.failed.add(text)
            raise Problem(503, "MODEL_UNAVAILABLE", "合成模型失败；材料保留。")
        self.responses[operation] = {
            "prompt": "根据本段材料，Self-Attention 的上下文向量如何组合输入信息？",
            "options": {
                "A": "始终只复制第一个输入向量。",
                "B": "删除所有输入向量后随机生成。",
                "C": "根据注意力权重组合输入向量。",
            },
            "correct_choice": "C",
            "rubric": ["评分提示：选择 C，并对照注意力权重与输入向量的关系。"],
            "basis": "Fake 模型答案依据：C 使用材料给出的注意力权重组合；A、B 没有对应依据。",
            "quote": text[:600],
            "block_id": source["block_id"],
        }
        return await super().generate_structured(
            operation, context, schema, max_output_units=max_output_units
        )
