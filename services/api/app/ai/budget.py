import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.openai_provider import SYSTEM, encode_context
from app.ai.provider import ModelContext
from app.core.config import Settings
from app.core.errors import Problem
from app.persistence.models import Job, ModelBudget, ModelCall


def reserve_upper_bound(context: ModelContext, schema: dict[str, object]) -> int:
    # UTF-8 bytes conservatively bound content tokens; schema/system and message framing included.
    return (
        len(encode_context(context).encode())
        + len(json.dumps(schema).encode())
        + len(SYSTEM.encode())
        + 4096
    )


async def reserve(
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    job: Job,
    context: ModelContext,
    schema: dict[str, object],
) -> ModelCall:
    amount = reserve_upper_bound(context, schema)
    day = datetime.now(UTC).date()
    async with factory.begin() as db:
        current = await db.scalar(select(Job).where(Job.id == job.id).with_for_update())
        if current is None or current.status != "RUNNING" or current.lease_id != job.lease_id:
            raise Problem(409, "MODEL_CANCELLED", "任务已取消。")
        for scope, calls_limit, token_limit in (
            ("GLOBAL", settings.model_global_calls_per_day, settings.model_global_tokens_per_day),
            (
                str(job.user_id),
                settings.model_user_calls_per_day,
                settings.model_user_tokens_per_day,
            ),
        ):
            key = int.from_bytes(
                hashlib.blake2b(("model-budget:" + scope).encode(), digest_size=8).digest(),
                "big",
                signed=True,
            )
            await db.execute(select(func.pg_advisory_xact_lock(key)))
            await db.execute(
                insert(ModelBudget)
                .values(
                    scope=scope,
                    day=day,
                    user_id=job.user_id if scope != "GLOBAL" else None,
                    calls=0,
                    reserved_tokens=0,
                )
                .on_conflict_do_nothing(index_elements=[ModelBudget.scope, ModelBudget.day])
            )
            row = await db.scalar(
                select(ModelBudget)
                .where(ModelBudget.scope == scope, ModelBudget.day == day)
                .with_for_update()
            )
            assert row is not None
            if row.calls >= calls_limit or row.reserved_tokens + amount > token_limit:
                raise Problem(
                    429, "MODEL_DAILY_BUDGET", "今日云模型预算已达到上限，可继续使用本地阅读方法。"
                )
            row.calls += 1
            row.reserved_tokens += amount
        if await db.scalar(
            select(ModelCall.id).where(
                ModelCall.job_id == job.id, ModelCall.attempt == job.attempt_count
            )
        ):
            raise Problem(409, "MODEL_ATTEMPT_USED", "本次模型调用可能已执行，请核对任务状态。")
        row_call = ModelCall(
            user_id=job.user_id, job_id=job.id, attempt=job.attempt_count, reserved_tokens=amount
        )
        db.add(row_call)
        await db.flush()
        return row_call
