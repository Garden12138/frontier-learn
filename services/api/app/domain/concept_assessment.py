"""Model-proposed concept questions. Exact citation checks do not establish semantic truth."""

import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.budget import reserve
from app.ai.provider import LLMProvider, ModelContext, check_model_access
from app.api.jobs import JobResponse
from app.auth.dependencies import get_owned
from app.core.config import Settings
from app.core.errors import Problem
from app.domain.assessment_types import AssessmentQuestion, AssessmentResponse, ConceptQuestion
from app.domain.tutoring_types import PageSnapshot
from app.jobs.service import Handler, enqueue
from app.persistence.models import Assessment, Job, LearningSession, ModelCall, User


async def assessment_response(db: AsyncSession, row: Assessment) -> AssessmentResponse:
    response = AssessmentResponse.model_validate(row)
    if row.question_job_id:
        job = await get_owned(db, Job, row.user_id, row.question_job_id)
        response.job = JobResponse.model_validate(job)
    return response


async def enqueue_question(db: AsyncSession, row: Assessment) -> None:
    job = await enqueue(
        db,
        user_id=row.user_id,
        kind="ASSESSMENT_QUESTION",
        idempotency_key=row.id.hex,
        payload={"assessment_id": str(row.id)},
        budget_units=3,
        max_attempts=3,
        timeout_seconds=30,
    )
    row.question_job_id = job.id


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
            question = AssessmentQuestion.model_validate(row.question)
            page = PageSnapshot.model_validate(session.page)
            block = next(b for b in page.blocks if b.id == question.block_id)
            excerpt = block.text[:1800]
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
                select(Job).where(Job.id == job.id, Job.user_id == job.user_id).with_for_update()
            )
            if (
                current is None
                or current.status != "RUNNING"
                or current.lease_id != job.lease_id
                or current.deadline_at <= datetime.now(UTC)
            ):
                return {}
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
