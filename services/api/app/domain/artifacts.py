import hashlib
import re
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_owned
from app.core.errors import Problem
from app.domain.assessment_types import AssessmentFeedback, AssessmentQuestion
from app.domain.tutoring_types import PageSnapshot
from app.persistence.models import Assessment, Job, LearningArtifact, LearningSession


def fenced(text: str) -> str:
    fence = "`" * max(3, max((len(s) + 1 for s in re.findall(r"`+", text)), default=3))
    return f"{fence}text\n{text}\n{fence}"


def content_hash(markdown: str) -> str:
    return hashlib.sha256(markdown.encode()).hexdigest()


async def create_artifact(db: AsyncSession, user_id: UUID, assessment_id: UUID) -> LearningArtifact:
    assessment = await get_owned(db, Assessment, user_id, assessment_id)
    await db.refresh(assessment, with_for_update=True)
    row = await db.scalar(
        select(LearningArtifact).where(
            LearningArtifact.user_id == user_id, LearningArtifact.assessment_id == assessment_id
        )
    )
    if row:
        return row
    if assessment.feedback is None:
        raise Problem(409, "ANSWER_REQUIRED", "请先完成短测并复查评价。")
    session = await get_owned(db, LearningSession, user_id, assessment.session_id)
    page = PageSnapshot.model_validate(session.page)
    question = AssessmentQuestion.model_validate(assessment.question)
    feedback = AssessmentFeedback.model_validate(assessment.feedback)
    answered_at = feedback.answered_at.isoformat() if feedback.answered_at else "旧记录未记录"
    title = assessment.concept_name[:200]
    markdown = (
        "\n\n".join(
            [
                "# 学习笔记草稿",
                "## 主题\n" + fenced(title),
                "## 来源\n"
                + fenced(
                    f"{page.title}\n{page.url or '用户手动提供，外部来源未验证'}\n"
                    f"范围：{page.scope}；快照块：{question.block_id}"
                ),
                "## 原文摘录\n" + fenced(question.excerpt),
                "## 当前理解（待验证）\n本次仅检查原文与推断的边界，尚未验证主题概念理解或应用。",
                "## 验证记录\n"
                + fenced(
                    f"题目：{question.prompt}\n作答：{assessment.answer}\n"
                    f"评价：{feedback.result}\n依据：{feedback.basis}\n"
                    f"时间：{assessment.created_at.isoformat()}\n"
                    f"作答时间：{answered_at}\n"
                    f"证据确认：{'已确认' if assessment.confirmed_at else '未确认'}"
                ),
                "## 学习步骤\n1. 对照摘录复述主张。\n"
                "2. 补充自己的例子与反例。\n3. 对照独立来源验证边界。",
                "## 限制与不确定性\n" + feedback.uncertainty,
                "## 未解疑问\n- 该结论在什么条件下成立？\n- 能否用独立的例子解释并检验？",
            ]
        )
        + "\n"
    )
    row = LearningArtifact(
        user_id=user_id, assessment_id=assessment_id, title=title, markdown=markdown
    )
    db.add(row)
    await db.flush()
    return row


async def ensure_editable(
    db: AsyncSession, row: LearningArtifact, version: int, *, reconcile: bool = False
) -> None:
    await db.refresh(row, with_for_update=True)
    if row.version != version:
        raise Problem(409, "ARTIFACT_CONFLICT", "草稿已变化，请刷新后重新审核。")
    job = await db.get(Job, row.job_id) if row.job_id else None
    if row.pr_number or (
        job
        and (
            not reconcile
            or job.error_code not in {"WRITE_BASE_CONFLICT", "WRITE_PERMISSION", "WRITE_REVOKED"}
        )
    ):
        raise Problem(
            409, "WRITEBACK_LOCKED", "此草稿已有写回操作，请先核对任务或 PR；可下载后另存。"
        )
