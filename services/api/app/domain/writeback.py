from collections.abc import Callable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.connectors.github_app import GitHubAppClient
from app.connectors.github_writeback import GitHubWriteback, WriteTransport
from app.core.config import Settings
from app.core.errors import Problem
from app.core.security import TokenVault
from app.domain.artifact_types import WritePreview
from app.domain.artifacts import content_hash
from app.ingestion.http_reader import PinnedHTTPReader, ReadResponse
from app.jobs.service import Handler
from app.persistence.models import (
    Assessment,
    GitHubConnection,
    Job,
    KnowledgeSource,
    LearningArtifact,
    LearningSession,
    SourceDocument,
)


class GuardedTransport:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        job: Job,
        preview: WritePreview,
        transport: WriteTransport,
    ) -> None:
        self.factory, self.job, self.preview, self.transport = factory, job, preview, transport

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        max_bytes: int,
        content: bytes = b"",
    ) -> ReadResponse:
        # Revocation/cancellation serialize with each external request, rather than a whole job.
        async with self.factory.begin() as db:
            source = await db.scalar(
                select(KnowledgeSource)
                .where(
                    KnowledgeSource.id == self.preview.source_id,
                    KnowledgeSource.user_id == self.job.user_id,
                )
                .with_for_update()
            )
            job = await db.scalar(select(Job).where(Job.id == self.job.id).with_for_update())
            artifact = await db.get(LearningArtifact, UUID(str(self.job.payload["artifact_id"])))
            if (
                source is None
                or source.status != "CONNECTED"
                or source.version != self.preview.source_version
                or not (source.encrypted_write_credential or source.github_connection_id)
                or source.write_scope == []
            ):
                raise Problem(403, "WRITE_REVOKED", "写入授权已变化；请重新审核授权。")
            if source.github_connection_id:
                connection = await db.get(GitHubConnection, source.github_connection_id)
                if (
                    connection is None
                    or connection.user_id != self.job.user_id
                    or connection.status != "CONNECTED"
                ):
                    raise Problem(403, "WRITE_REVOKED", "GitHub 连接已撤销。")
            if (
                job is None
                or job.status != "RUNNING"
                or job.lease_id != self.job.lease_id
                or artifact is None
                or artifact.user_id != self.job.user_id
            ):
                raise Problem(409, "WRITE_CANCELLED", "写回已取消或草稿已删除。")
            if (
                artifact.job_id != job.id
                or artifact.version != self.job.payload["version"]
                or content_hash(artifact.markdown) != self.preview.content_hash
            ):
                raise Problem(409, "ARTIFACT_CONFLICT", "草稿已变化，请重新审核。")
            return await self.transport.request(
                method, url, headers=headers, max_bytes=max_bytes, content=content
            )


def writeback_handler(
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    transport_factory: Callable[[], WriteTransport] | None = None,
    app_client_factory: Callable[[], GitHubAppClient] | None = None,
) -> Handler:
    async def handle(job: Job) -> dict[str, object]:
        if not settings.writeback_enabled:
            raise Problem(403, "WRITEBACK_DISABLED", "部署尚未启用写回。")
        async with factory.begin() as db:
            artifact = await db.get(LearningArtifact, UUID(str(job.payload["artifact_id"])))
            if artifact is None or artifact.user_id != job.user_id or artifact.preview is None:
                raise Problem(404, "NOT_FOUND", "草稿不存在。")
            preview = WritePreview.model_validate(artifact.preview)
            source = await db.get(KnowledgeSource, preview.source_id)
            if (
                source is None
                or source.user_id != job.user_id
                or not (source.encrypted_write_credential or source.github_connection_id)
            ):
                raise Problem(403, "WRITE_REVOKED", "写入授权已撤销。")
            if source.github_connection_id:
                github = app_client_factory() if app_client_factory else GitHubAppClient(settings)
                token = await github.source_token(db, source, write=True)
            else:
                assert source.encrypted_write_credential
                token = TokenVault(settings.encryption_key).decrypt(
                    source.encrypted_write_credential
                )
            markdown = artifact.markdown
        transport = (
            transport_factory()
            if transport_factory
            else PinnedHTTPReader(frozenset({"api.github.com"}))
        )
        connector = GitHubWriteback(
            preview.repository, token, GuardedTransport(factory, job, preview, transport)
        )
        pull = await connector.create_pr(
            branch=preview.branch,
            base=preview.base_branch,
            base_sha=preview.base_sha,
            path=preview.path,
            file_sha=preview.file_sha,
            markdown=markdown,
            marker=(
                f"FrontierLearn artifact {artifact.id} version {artifact.version} "
                f"{preview.content_hash}"
            ),
        )
        number = pull.get("number")
        if not isinstance(number, int) or number < 1:
            raise Problem(502, "GITHUB_INVALID_RESPONSE", "PR 编号无效，请重试核对。")
        async with factory.begin() as db:
            current = await db.scalar(
                select(LearningArtifact)
                .where(LearningArtifact.id == artifact.id, LearningArtifact.user_id == job.user_id)
                .with_for_update()
            )
            # Keep a known remote result visible even if cancellation raced the last response.
            if current is not None and current.job_id == job.id:
                current.pr_number = number
                current.pr_url = f"https://github.com/{preview.repository}/pull/{number}"
        return {"artifact_id": str(artifact.id), "pr_number": number}

    return handle


async def after_reindex(db: AsyncSession, job: Job) -> None:
    from datetime import UTC, datetime

    from app.domain.replanning import replan_after_evidence

    if not isinstance(job.payload.get("artifact_id"), str):
        return
    artifact = await db.get(LearningArtifact, UUID(str(job.payload["artifact_id"])))
    if (
        artifact is None
        or artifact.user_id != job.user_id
        or artifact.merged_at is None
        or artifact.reindexed_at is not None
        or artifact.preview is None
    ):
        return
    preview = WritePreview.model_validate(artifact.preview)
    document = await db.scalar(
        select(SourceDocument).where(
            SourceDocument.source_id == job.source_id,
            SourceDocument.user_id == job.user_id,
            SourceDocument.path == preview.path,
            SourceDocument.is_current.is_(True),
            SourceDocument.deleted_at.is_(None),
            SourceDocument.content_hash == preview.content_hash,
        )
    )
    if document is None:
        return
    assessment = await db.get(Assessment, artifact.assessment_id)
    session = await db.get(LearningSession, assessment.session_id) if assessment else None
    artifact.reindexed_at = datetime.now(UTC)
    await replan_after_evidence(
        db,
        job.user_id,
        session.goal_id if session else None,
        f"笔记草稿 {artifact.id} 的 PR 已由用户合并，文件版本 {document.revision} 已重新索引。"
        "后续建议结合新笔记与已确认短测；笔记仍只是学习线索，不证明掌握。",
    )
