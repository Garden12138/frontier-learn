import asyncio
import hashlib
import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import Problem
from app.persistence.models import Job

logger = logging.getLogger("frontier.jobs")


@dataclass(frozen=True)
class PartialResult:
    result: dict[str, object]
    error_code: str


Handler = Callable[[Job], Awaitable[dict[str, object] | PartialResult]]


async def enqueue(
    db: AsyncSession,
    *,
    user_id: UUID,
    kind: str,
    idempotency_key: str,
    payload: dict[str, object],
    source_id: UUID | None = None,
    budget_units: int = 20,
    max_attempts: int = 3,
    timeout_seconds: int = 60,
) -> Job:
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", idempotency_key):
        raise Problem(400, "INVALID_IDEMPOTENCY_KEY", "请提供 8–128 位操作标识。")
    if (
        not 1 <= budget_units <= 1000
        or not 1 <= max_attempts <= 3
        or not 1 <= timeout_seconds <= 120
    ):
        raise Problem(400, "JOB_LIMIT", "任务预算、超时或重试次数超过允许范围。")
    encoded = json.dumps({"payload": payload, "source_id": str(source_id)}, sort_keys=True)
    if len(encoded.encode()) > 16_384:
        raise Problem(413, "JOB_PAYLOAD_LIMIT", "任务参数过大，请缩小导入范围。")
    request_hash = hashlib.sha256(encoded.encode()).hexdigest()
    now = datetime.now(UTC)
    await db.execute(
        insert(Job)
        .values(
            user_id=user_id,
            source_id=source_id,
            kind=kind,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            payload=payload,
            budget_units=budget_units,
            max_attempts=max_attempts,
            timeout_seconds=timeout_seconds,
            deadline_at=now + timedelta(minutes=5),
            next_attempt_at=now,
        )
        .on_conflict_do_nothing(index_elements=[Job.user_id, Job.kind, Job.idempotency_key])
    )
    result = await db.scalar(
        select(Job).where(
            Job.user_id == user_id, Job.kind == kind, Job.idempotency_key == idempotency_key
        )
    )
    assert result is not None
    if result.request_hash != request_hash:
        raise Problem(409, "IDEMPOTENCY_CONFLICT", "此操作标识已用于不同的请求内容。")
    return result


async def retry_job(db: AsyncSession, job: Job) -> Job:
    now = datetime.now(UTC)
    if job.status not in {"FAILED", "PARTIAL"}:
        raise Problem(409, "JOB_NOT_RETRYABLE", "仅失败或部分失败的任务可以重试。")
    if job.attempt_count >= job.max_attempts or job.spent_units >= job.budget_units:
        raise Problem(409, "JOB_LIMIT", "任务已达到尝试或预算上限。")
    if job.deadline_at <= now:
        raise Problem(409, "JOB_EXPIRED", "任务已超过截止时间，请发起新的操作。")
    job.status = "PENDING"
    job.next_attempt_at = now + timedelta(seconds=2**job.attempt_count)
    job.finished_at = None
    job.error_code = None
    return job


async def cancel_job(db: AsyncSession, job: Job) -> Job:
    if job.status in {"PENDING", "RUNNING"}:
        job.status = "CANCELLED"
        job.finished_at = datetime.now(UTC)
        job.lease_id = None
    return job


async def run_one(factory: async_sessionmaker[AsyncSession], handlers: dict[str, Handler]) -> bool:
    now = datetime.now(UTC)
    async with factory.begin() as db:
        # A crashed worker's lease does not permit another unbounded automatic attempt.
        await db.execute(
            update(Job)
            .where(Job.status == "RUNNING", Job.lease_expires_at <= now)
            .values(
                status="FAILED", error_code="WORKER_LEASE_EXPIRED", finished_at=now, lease_id=None
            )
        )
        await db.execute(
            update(Job)
            .where(Job.status == "PENDING", Job.deadline_at <= now)
            .values(status="FAILED", error_code="JOB_EXPIRED", finished_at=now)
        )
        job = await db.scalar(
            select(Job)
            .where(Job.status == "PENDING", Job.next_attempt_at <= now)
            .order_by(Job.created_at, Job.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if job is None:
            return False
        if job.attempt_count >= job.max_attempts or job.spent_units >= job.budget_units:
            job.status = "FAILED"
            job.error_code = "JOB_LIMIT"
            job.finished_at = now
            return True
        job.status = "RUNNING"
        job.attempt_count += 1
        job.spent_units += 1
        job.started_at = now
        job.lease_id = uuid4()
        job.lease_expires_at = min(
            now + timedelta(seconds=job.timeout_seconds + 5), job.deadline_at
        )
        job_id, lease_id = job.id, job.lease_id

    status = "SUCCEEDED"
    error_code: str | None = None
    result: dict[str, object] = {}
    handler = handlers.get(job.kind)
    try:
        if handler is None:
            raise Problem(400, "UNSUPPORTED_JOB", "该任务类型尚不支持。")
        remaining = max(0.001, min(job.timeout_seconds, (job.deadline_at - now).total_seconds()))
        async with asyncio.timeout(remaining):
            outcome = await handler(job)
            if isinstance(outcome, PartialResult):
                status, error_code, result = "PARTIAL", outcome.error_code, outcome.result
            else:
                result = outcome
    except Problem as exc:
        status, error_code = "FAILED", exc.code
    except TimeoutError:
        status, error_code = "FAILED", "JOB_TIMEOUT"
    except Exception:
        status, error_code = "FAILED", "JOB_FAILED"
    async with factory.begin() as db:
        # A revoked lease or cancellation wins over late handler completion.
        final_status = await db.scalar(
            update(Job)
            .where(Job.id == job_id, Job.status == "RUNNING", Job.lease_id == lease_id)
            .values(
                status=status,
                error_code=error_code,
                result=result,
                lease_id=None,
                finished_at=datetime.now(UTC),
                progress=1.0 if status in {"SUCCEEDED", "PARTIAL"} else Job.progress,
            )
            .returning(Job.status)
        )
        if final_status is None:
            final_status = await db.scalar(select(Job.status).where(Job.id == job_id)) or "REMOVED"
    logger.info(
        json.dumps(
            {
                "event": "job_finished",
                "task_id": str(job_id),
                "status": final_status,
                "error_code": error_code,
            }
        )
    )
    return True
