import difflib
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Request
from sqlalchemy import select

from app.api.jobs import JobResponse
from app.auth.dependencies import CurrentUser, Db, get_owned
from app.connectors.base import SourceScope
from app.connectors.github import normalize_prefixes, within_scope
from app.connectors.github_app import GitHubAppClient
from app.connectors.github_writeback import GitHubWriteback, note_path
from app.core.errors import Problem
from app.core.security import TokenVault
from app.domain.artifact_types import (
    ArtifactCreate,
    ArtifactEdit,
    ArtifactResponse,
    PreviewRequest,
    WriteApproval,
    WritePermission,
    WritePreview,
)
from app.domain.artifacts import content_hash, create_artifact, ensure_editable
from app.ingestion.http_reader import PinnedHTTPReader
from app.jobs.service import enqueue
from app.persistence.models import AuditEvent, Job, KnowledgeSource, LearningArtifact

router = APIRouter(tags=["Artifacts"])


async def connector(request: Request, source: KnowledgeSource, db: Db) -> GitHubWriteback:
    if (
        not request.app.state.settings.writeback_enabled
        or not (source.encrypted_write_credential or source.github_connection_id)
        or not source.write_scope
        or source.status != "CONNECTED"
    ):
        raise Problem(
            403, "WRITE_PERMISSION", "需先由服务端启用写回，并对该仓库单独授予笔记目录写入权限。"
        )
    transport = getattr(request.app.state, "write_transport", None) or PinnedHTTPReader(
        frozenset({"api.github.com"})
    )
    if source.github_connection_id:
        app_client = GitHubAppClient(
            request.app.state.settings, getattr(request.app.state, "github_app_transport", None)
        )
        token = await app_client.source_token(db, source, write=True)
    else:
        assert source.encrypted_write_credential
        token = TokenVault(request.app.state.settings.encryption_key).decrypt(
            source.encrypted_write_credential
        )
    return GitHubWriteback(source.external_ref, token, transport)


@router.get("/artifacts", response_model=list[ArtifactResponse])
async def artifacts(user: CurrentUser, db: Db) -> list[ArtifactResponse]:
    rows = await db.scalars(
        select(LearningArtifact)
        .where(LearningArtifact.user_id == user.id)
        .order_by(LearningArtifact.created_at.desc())
        .limit(100)
    )
    return [ArtifactResponse.model_validate(row) for row in rows]


@router.post("/artifacts", response_model=ArtifactResponse, status_code=201)
async def create(body: ArtifactCreate, user: CurrentUser, db: Db) -> ArtifactResponse:
    row = await create_artifact(db, user.id, body.assessment_id)
    await db.commit()
    return ArtifactResponse.model_validate(row)


@router.get("/artifacts/{artifact_id}", response_model=ArtifactResponse)
async def get(artifact_id: UUID, user: CurrentUser, db: Db) -> ArtifactResponse:
    return ArtifactResponse.model_validate(
        await get_owned(db, LearningArtifact, user.id, artifact_id)
    )


@router.put("/artifacts/{artifact_id}", response_model=ArtifactResponse)
async def edit(
    artifact_id: UUID, body: ArtifactEdit, user: CurrentUser, db: Db
) -> ArtifactResponse:
    row = await get_owned(db, LearningArtifact, user.id, artifact_id)
    await ensure_editable(db, row, body.version)
    row.markdown, row.version, row.preview = body.markdown, row.version + 1, None
    await db.commit()
    return ArtifactResponse.model_validate(row)


@router.post("/artifacts/{artifact_id}/preview", response_model=ArtifactResponse)
async def preview(
    artifact_id: UUID, body: PreviewRequest, user: CurrentUser, db: Db, request: Request
) -> ArtifactResponse:
    source = await get_owned(db, KnowledgeSource, user.id, body.source_id)
    await db.refresh(source, with_for_update=True)
    row = await get_owned(db, LearningArtifact, user.id, artifact_id)
    await ensure_editable(db, row, body.version, reconcile=True)
    path = note_path(body.path)
    if not within_scope(
        path, SourceScope(source.external_ref, tuple(source.write_scope))
    ) or not within_scope(path, SourceScope(source.external_ref, tuple(source.path_prefixes))):
        raise Problem(403, "WRITE_SCOPE", "目标文件不在已授权的读写目录中。")
    github = await connector(request, source, db)
    if row.job_id and row.preview:
        old = WritePreview.model_validate(row.preview)
        marker = f"FrontierLearn artifact {row.id} version {row.version} {old.content_hash}"
        existing = await github.existing_pull(old.branch, old.base_branch, marker)
        if existing is not None:
            number = existing.get("number")
            if not isinstance(number, int):
                raise Problem(502, "GITHUB_INVALID_RESPONSE", "PR 编号无效。")
            row.pr_number = number
            row.pr_url = f"https://github.com/{old.repository}/pull/{number}"
            await db.commit()
            return ArtifactResponse.model_validate(row)
    repo = await github.obj("GET")
    branch = repo.get("default_branch")
    if not isinstance(branch, str) or not branch or len(branch) > 200:
        raise Problem(502, "GITHUB_INVALID_RESPONSE", "仓库默认分支无效。")
    base_sha = await github.head(branch)
    file_sha, original = await github.file(path, base_sha)
    if body.mode == "NEW" and file_sha:
        raise Problem(409, "FILE_EXISTS", "该文件已存在，请选择手工合并并审核完整 Diff。")
    if body.mode == "MANUAL_MERGE" and file_sha is None:
        raise Problem(409, "FILE_MISSING", "合并目标不存在，请选择新建笔记。")
    diff = "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            row.markdown.splitlines(keepends=True),
            fromfile=path,
            tofile=path,
        )
    )
    if not diff:
        raise Problem(409, "NO_CHANGES", "草稿与目标内容相同，无需写回。")
    row.version += 1
    row.job_id = None
    row.preview = WritePreview(
        source_id=source.id,
        source_version=source.version,
        repository=source.external_ref,
        path=path,
        mode=body.mode,
        base_branch=branch,
        base_sha=base_sha,
        file_sha=file_sha,
        branch=f"frontierlearn/{row.id}-v{row.version}",
        diff=diff,
        content_hash=content_hash(row.markdown),
    ).model_dump(mode="json")
    await db.commit()
    return ArtifactResponse.model_validate(row)


@router.post("/artifacts/{artifact_id}/approve", response_model=JobResponse, status_code=202)
async def approve(
    artifact_id: UUID,
    body: WriteApproval,
    user: CurrentUser,
    db: Db,
    request: Request,
    key: Annotated[str, Header(alias="Idempotency-Key")],
) -> JobResponse:
    row = await get_owned(db, LearningArtifact, user.id, artifact_id)
    if row.preview is None:
        raise Problem(409, "PREVIEW_REQUIRED", "请先预览当前草稿的 Diff。")
    checked = WritePreview.model_validate(row.preview)
    source = await get_owned(db, KnowledgeSource, user.id, checked.source_id)
    await db.refresh(source, with_for_update=True)
    await db.refresh(row, with_for_update=True)
    await connector(request, source, db)
    if (
        row.version != body.version
        or source.version != checked.source_version
        or content_hash(row.markdown) != checked.content_hash
    ):
        raise Problem(409, "WRITE_CONFLICT", "草稿或授权已变化，请重新预览审核。")
    if row.job_id:
        job = await get_owned(db, Job, user.id, row.job_id)
        return JobResponse.model_validate(job)
    job = await enqueue(
        db,
        user_id=user.id,
        source_id=source.id,
        kind="GITHUB_WRITEBACK",
        idempotency_key=key,
        payload={
            "artifact_id": str(row.id),
            "version": row.version,
            "source_version": source.version,
        },
        budget_units=3,
        timeout_seconds=120,
    )
    row.job_id = job.id
    db.add(
        AuditEvent(
            user_id=user.id,
            operation="WRITEBACK_APPROVED",
            object_type="artifact",
            object_id=str(row.id),
            summary_code="EXPLICIT_DIFF_APPROVAL",
        )
    )
    await db.commit()
    return JobResponse.model_validate(job)


@router.post("/artifacts/{artifact_id}/reindex", response_model=JobResponse, status_code=202)
async def reindex(
    artifact_id: UUID, body: WriteApproval, user: CurrentUser, db: Db, request: Request
) -> JobResponse:
    row = await get_owned(db, LearningArtifact, user.id, artifact_id)
    if row.preview is None or row.pr_number is None:
        raise Problem(409, "PR_REQUIRED", "请先创建并在 GitHub 审核合并 PR。")
    checked = WritePreview.model_validate(row.preview)
    source = await get_owned(db, KnowledgeSource, user.id, checked.source_id)
    await db.refresh(source, with_for_update=True)
    await db.refresh(row, with_for_update=True)
    if row.version != body.version:
        raise Problem(409, "ARTIFACT_CONFLICT", "草稿版本已变化。")
    github = await connector(request, source, db)
    pull = await github.obj("GET", f"/pulls/{row.pr_number}")
    head, base = pull.get("head"), pull.get("base")
    if (
        pull.get("merged") is not True
        or not isinstance(head, dict)
        or head.get("ref") != checked.branch
        or not isinstance(base, dict)
        or base.get("ref") != checked.base_branch
        or not isinstance(base.get("repo"), dict)
        or base["repo"].get("full_name", "").lower() != checked.repository.lower()
    ):
        raise Problem(409, "PR_NOT_MERGED", "PR 尚未合并或来源不匹配，不会增加笔记证据。")
    from app.connectors.github_writeback import sha

    _, merged_text = await github.file(checked.path, sha(pull.get("merge_commit_sha")))
    if content_hash(merged_text) != checked.content_hash:
        raise Problem(409, "MERGED_CONTENT_CHANGED", "合并结果与审核稿不同，请手工检查后同步来源。")
    active = await db.get(Job, source.active_job_id) if source.active_job_id else None
    if active and active.status in {"PENDING", "RUNNING"}:
        raise Problem(409, "SYNC_IN_PROGRESS", "来源正在同步，请稍后核对合并结果。")
    job = await enqueue(
        db,
        user_id=user.id,
        source_id=source.id,
        kind="GITHUB_SYNC",
        idempotency_key=f"merged-{row.id}-s{source.version}",
        payload={"source_version": source.version, "artifact_id": str(row.id)},
        timeout_seconds=120,
        budget_units=3,
    )
    row.merged_at = row.merged_at or datetime.now(UTC)
    source.active_job_id = job.id
    await db.commit()
    return JobResponse.model_validate(job)


@router.put("/sources/{source_id}/write-permission", status_code=204)
async def grant(
    source_id: UUID, body: WritePermission, user: CurrentUser, db: Db, request: Request
) -> None:
    if not request.app.state.settings.writeback_enabled:
        raise Problem(403, "WRITEBACK_DISABLED", "部署尚未启用写回。")
    source = await get_owned(db, KnowledgeSource, user.id, source_id)
    await db.refresh(source, with_for_update=True)
    if source.version != body.version or source.status != "CONNECTED":
        raise Problem(409, "SOURCE_CONFLICT", "请刷新已连接的来源后重新授权。")
    prefixes = normalize_prefixes(body.path_prefixes)
    if not prefixes:
        raise Problem(400, "WRITE_SCOPE", "必须限定至少一个笔记目录。")
    source.encrypted_write_credential = TokenVault(
        request.app.state.settings.encryption_key
    ).encrypt(body.credential)
    source.write_scope, source.version = prefixes, source.version + 1
    db.add(
        AuditEvent(
            user_id=user.id,
            operation="WRITE_PERMISSION_GRANTED",
            object_type="source",
            object_id=str(source.id),
            summary_code="SEPARATE_SCOPED_CREDENTIAL",
        )
    )
    await db.commit()


@router.delete("/sources/{source_id}/write-permission", status_code=204)
async def revoke(source_id: UUID, user: CurrentUser, db: Db) -> None:
    source = await get_owned(db, KnowledgeSource, user.id, source_id)
    await db.refresh(source, with_for_update=True)
    source.encrypted_write_credential, source.write_scope = None, []
    source.version += 1
    await db.commit()
