"""Model-proposed concept questions. Exact citation checks do not establish semantic truth."""

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.budget import reserve
from app.ai.provider import LLMProvider, ModelContext, check_model_access
from app.api.jobs import JobResponse
from app.auth.dependencies import get_owned
from app.core.config import Settings
from app.core.errors import Problem
from app.domain.assessment_types import (
    AssessmentQuestion,
    AssessmentRegenerate,
    AssessmentResponse,
    ConceptQuestion,
    option_quality_notice,
)
from app.domain.tutoring_types import PageSnapshot
from app.jobs.service import Handler, enqueue
from app.persistence.models import Assessment, Job, LearningSession, ModelCall, User


async def assessment_response(db: AsyncSession, row: Assessment) -> AssessmentResponse:
    response = AssessmentResponse.model_validate(row)
    if row.answer is None:
        response.question.rubric = []
    if row.question_job_id:
        job = await get_owned(db, Job, row.user_id, row.question_job_id)
        response.job = JobResponse.model_validate(job)
    return response


async def enqueue_question(db: AsyncSession, row: Assessment, recovery_version: int = 0) -> None:
    job = await enqueue(
        db,
        user_id=row.user_id,
        kind="ASSESSMENT_QUESTION",
        idempotency_key=f"{row.id.hex}_{recovery_version}",
        payload={"assessment_id": str(row.id), "recovery_version": recovery_version},
        budget_units=1,
        max_attempts=1,
        timeout_seconds=30,
    )
    row.question_job_id = job.id


async def regenerate_question(
    db: AsyncSession, row: Assessment, body: AssessmentRegenerate
) -> None:
    # Same Job -> Assessment lock order as the worker result publication.
    old = (
        await get_owned(db, Job, row.user_id, row.question_job_id) if row.question_job_id else None
    )
    if old:
        await db.refresh(old, with_for_update=True)
    await db.refresh(row, with_for_update=True)
    user = await db.get(User, row.user_id)
    if not user or not user.cloud_processing_allowed:
        raise Problem(403, "MODEL_CONSENT_REQUIRED", "恢复拟题需要重新确认模型处理授权。")
    if row.answer is not None or row.question.get("scope") != "CONCEPT_CHECK":
        raise Problem(409, "ASSESSMENT_CONFLICT", "已作答或其他类型短测不能重新生成。")
    if row.version == body.version + 1 and row.question_job_id:
        active = await db.get(Job, row.question_job_id, populate_existing=True)
        if active and active.payload.get("recovery_version") == body.version:
            return
    if row.version != body.version or not old or old.id != row.question_job_id:
        raise Problem(409, "ASSESSMENT_CONFLICT", "短测版本已变化，请刷新后再操作。")
    if old.status not in {"FAILED", "CANCELLED"}:
        raise Problem(409, "QUESTION_NOT_RECOVERABLE", "只有失败或取消的拟题可以恢复。")
    jobs = list(
        await db.scalars(
            select(Job).where(
                Job.user_id == row.user_id,
                Job.kind == "ASSESSMENT_QUESTION",
                Job.payload["assessment_id"].as_string() == str(row.id),
            )
        )
    )
    if sum(max(1, job.attempt_count) for job in jobs) >= 3:
        raise Problem(409, "QUESTION_ATTEMPT_LIMIT", "本短测已达三次尝试上限，请从新学习会话开始。")
    old.lease_id = None
    row.cloud_processing_allowed = True
    # Preserve selection and previously generated material; never overwrite an answer.
    await enqueue_question(db, row, body.version)
    row.version += 1


def concept_handler(
    factory: async_sessionmaker[AsyncSession],
    provider: LLMProvider | None,
    settings: Settings,
) -> Handler:
    async def handle(job: Job) -> dict[str, object]:
        if provider is None:
            raise Problem(503, "MODEL_UNAVAILABLE", "概念拟题模型未配置，可继续使用来源边界题。")
        async with factory() as db:
            row = await get_owned(
                db, Assessment, job.user_id, UUID(str(job.payload["assessment_id"]))
            )
            session = await get_owned(db, LearningSession, job.user_id, row.session_id)
            user = await db.get(User, job.user_id)
            if not user or not user.cloud_processing_allowed or not row.cloud_processing_allowed:
                raise Problem(403, "MODEL_CONSENT_REQUIRED", "概念拟题需要本次与全局模型处理授权。")
            current = await db.get(Job, job.id)
            if (
                not current
                or current.status != "RUNNING"
                or current.lease_id != job.lease_id
                or row.question_job_id != job.id
                or row.answer is not None
            ):
                return {}
            question = AssessmentQuestion.model_validate(row.question)
            page = PageSnapshot.model_validate(session.page)
            block = next(b for b in page.blocks if b.id == question.block_id)
            excerpt = question.source_excerpt or block.text[:1800]
            context = ModelContext(
                user_goal=row.concept_name,
                untrusted_text=json.dumps(
                    {"block_id": block.id, "source_excerpt": excerpt}, ensure_ascii=False
                ),
                cloud_processing_allowed=True,
            )
            check_model_access(provider, context)
            reservation = (
                await reserve(factory, settings, job, context, ConceptQuestion.model_json_schema())
                if provider.name == "openai_responses"
                else None
            )
            generated = await provider.generate_structured(
                "concept_question", context, ConceptQuestion, max_output_units=4096
            )
            candidate = generated.output
            if candidate.block_id != block.id or candidate.quote not in excerpt:
                raise Problem(
                    503, "QUESTION_CITATION_INVALID", "模型题目没有可匹配的原文依据，未保存题目。"
                )
            if generated.output_units > 4096 or len(candidate.model_dump_json()) > 4096:
                raise Problem(503, "MODEL_BUDGET", "题目超过本次输出预算。")
            current = await db.scalar(
                select(Job)
                .where(Job.id == job.id, Job.user_id == job.user_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if (
                current is None
                or current.status != "RUNNING"
                or current.lease_id != job.lease_id
                or current.deadline_at <= datetime.now(UTC)
                or current.lease_expires_at is None
                or current.lease_expires_at <= datetime.now(UTC)
                or current.started_at is None
                or current.started_at + timedelta(seconds=current.timeout_seconds)
                <= datetime.now(UTC)
            ):
                raise Problem(
                    409, "QUESTION_RESULT_EXPIRED", "任务授权或执行时间已失效，未保存迟到结果。"
                )
            await db.refresh(row, with_for_update=True)
            if row.question_job_id != job.id or row.answer is not None:
                return {}
            row.question = AssessmentQuestion(
                prompt=candidate.prompt,
                excerpt=candidate.quote,
                block_id=block.id,
                options=candidate.options.model_dump(),
                rubric=candidate.rubric,
                scope="CONCEPT_CHECK",
                source_excerpt=excerpt,
                source_reason=question.source_reason,
                quality_notice=option_quality_notice(candidate.options),
            ).model_dump(mode="json")
            row.grading = {
                "correct_choice": candidate.correct_choice,
                "basis": candidate.basis,
                "provider": generated.provider,
            }
            row.version += 1
            if reservation:
                call = await db.get(ModelCall, reservation.id)
                if call:
                    call.input_tokens, call.output_tokens = (
                        generated.input_tokens,
                        generated.output_tokens,
                    )
            await db.commit()
            return {"assessment_id": str(row.id)}

    return handle
