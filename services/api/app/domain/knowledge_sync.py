import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import PurePosixPath
from urllib.parse import quote

from pydantic import SecretStr
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.connectors.base import DocumentRef, KnowledgeConnector, SourceScope
from app.connectors.github import CODE_SUFFIXES, GitHubConnector, file_limit
from app.connectors.github_app import GitHubAppClient
from app.core.config import Settings
from app.core.errors import Problem
from app.core.security import MAX_BATCH_BYTES, TokenVault
from app.domain.knowledge_policy import lock_knowledge, refresh_states
from app.domain.writeback import after_reindex
from app.ingestion.evidence import extract_candidates
from app.ingestion.markdown import parse_text
from app.jobs.service import Handler, PartialResult
from app.persistence.models import (
    Job,
    KnowledgeConcept,
    KnowledgeEvidence,
    KnowledgeSource,
    KnowledgeState,
    SourceChunk,
    SourceDocument,
)

ConnectorFactory = Callable[[str, SecretStr | None], KnowledgeConnector]


async def _guard(db: AsyncSession, job: Job) -> KnowledgeSource:
    source = await db.scalar(
        select(KnowledgeSource)
        .where(KnowledgeSource.id == job.source_id, KnowledgeSource.user_id == job.user_id)
        .with_for_update()
    )
    current = await db.scalar(
        select(Job).where(Job.id == job.id, Job.user_id == job.user_id).with_for_update()
    )
    if (
        source is None
        or current is None
        or source.status != "CONNECTED"
        or source.active_job_id != job.id
        or source.version != job.payload.get("source_version")
        or current.status != "RUNNING"
        or current.lease_id != job.lease_id
        or current.deadline_at <= datetime.now(UTC)
    ):
        raise Problem(409, "SOURCE_SYNC_CANCELLED", "来源已暂停、断开或同步已取消。")
    return source


async def _retire(db: AsyncSession, document: SourceDocument) -> None:
    document.is_current = False
    document.deleted_at = datetime.now(UTC)
    await db.execute(
        update(KnowledgeEvidence)
        .where(
            KnowledgeEvidence.user_id == document.user_id,
            KnowledgeEvidence.document_id == document.id,
        )
        .values(status="RETRACTED")
    )


async def _save_document(
    db: AsyncSession,
    job: Job,
    ref: DocumentRef,
    revision: str,
    content: bytes | None,
    status: str,
    error: str | None,
    seen_paths: set[str],
) -> None:
    source = await _guard(db, job)
    await lock_knowledge(db, job.user_id)
    document = await db.scalar(
        select(SourceDocument).where(
            SourceDocument.source_id == source.id,
            SourceDocument.user_id == job.user_id,
            SourceDocument.path == ref.path,
            SourceDocument.blob_sha == ref.blob_sha,
        )
    )
    if document is None:
        document = SourceDocument(
            user_id=job.user_id,
            source_id=source.id,
            path=ref.path,
            revision=revision,
            blob_sha=ref.blob_sha,
            size_bytes=ref.size,
            parse_status=status,
        )
        db.add(document)
        await db.flush()
    document.parse_status, document.error_code = status, error
    document.deleted_at = None
    if status == "FAILED":
        previous_failures = await db.scalars(
            select(SourceDocument).where(
                SourceDocument.user_id == job.user_id,
                SourceDocument.source_id == source.id,
                SourceDocument.path == ref.path,
                SourceDocument.id != document.id,
                SourceDocument.parse_status == "FAILED",
                SourceDocument.deleted_at.is_(None),
            )
        )
        for previous in previous_failures:
            await _retire(db, previous)
        return
    old_versions = await db.scalars(
        select(SourceDocument).where(
            SourceDocument.source_id == source.id,
            SourceDocument.user_id == job.user_id,
            SourceDocument.path == ref.path,
            SourceDocument.id != document.id,
        )
    )
    for old in old_versions:
        await _retire(db, old)
    document.is_current = True
    document.revision = revision
    # A previously observed version can reappear after revert; rebuild its current citations once.
    await db.execute(
        delete(KnowledgeEvidence).where(
            KnowledgeEvidence.user_id == job.user_id, KnowledgeEvidence.document_id == document.id
        )
    )
    await db.execute(
        delete(SourceChunk).where(
            SourceChunk.user_id == job.user_id, SourceChunk.document_id == document.id
        )
    )
    if content is None:
        return
    text, chunks = parse_text(content, code=PurePosixPath(ref.path).suffix.lower() in CODE_SUFFIXES)
    document.content_text = text
    document.content_hash = hashlib.sha256(content).hexdigest()
    previous_copies = await db.scalars(
        select(SourceDocument).where(
            SourceDocument.user_id == job.user_id,
            SourceDocument.source_id == source.id,
            SourceDocument.blob_sha == ref.blob_sha,
            SourceDocument.id != document.id,
            SourceDocument.is_current.is_(True),
        )
    )
    for previous in previous_copies:
        if previous.path not in seen_paths:
            await _retire(db, previous)
        else:
            previous.parse_status, previous.error_code = "DUPLICATE", "DUPLICATE_CONTENT"
            await db.execute(
                update(KnowledgeEvidence)
                .where(
                    KnowledgeEvidence.user_id == job.user_id,
                    KnowledgeEvidence.document_id == previous.id,
                )
                .values(status="RETRACTED")
            )
    renamed = await db.scalar(
        select(SourceDocument.path)
        .where(
            SourceDocument.source_id == source.id,
            SourceDocument.user_id == job.user_id,
            SourceDocument.blob_sha == ref.blob_sha,
            SourceDocument.path.not_in(seen_paths),
        )
        .limit(1)
    )
    document.renamed_from = renamed
    chunk_rows: list[SourceChunk] = []
    for chunk in chunks:
        locator: dict[str, object] = {
            "provider": "github",
            "repository": source.external_ref,
            "commit_sha": revision,
            "path": ref.path,
            "line_start": chunk.line_start,
            "line_end": chunk.line_end,
            "offset_start": chunk.start,
            "offset_end": chunk.end,
            "url": (
                f"https://github.com/{source.external_ref}/blob/{revision}/"
                f"{quote(ref.path, safe='/')}#L{chunk.line_start}-L{chunk.line_end}"
            ),
        }
        row = SourceChunk(
            user_id=job.user_id,
            document_id=document.id,
            locator=locator,
            text_checksum=hashlib.sha256(chunk.text.encode()).hexdigest(),
            snippet=chunk.text[:1000],
            content_type=chunk.content_type,
        )
        db.add(row)
        chunk_rows.append(row)
    await db.flush()
    for candidate in extract_candidates(
        ref.path, text, chunks, code=PurePosixPath(ref.path).suffix.lower() in CODE_SUFFIXES
    ):
        await db.execute(
            insert(KnowledgeConcept)
            .values(canonical_name=candidate.canonical_name)
            .on_conflict_do_nothing(index_elements=[KnowledgeConcept.canonical_name])
        )
        concept = await db.scalar(
            select(KnowledgeConcept).where(
                KnowledgeConcept.canonical_name == candidate.canonical_name
            )
        )
        assert concept is not None
        await db.execute(
            insert(KnowledgeState)
            .values(user_id=job.user_id, concept_id=concept.id, name=candidate.name)
            .on_conflict_do_nothing(
                index_elements=[KnowledgeState.user_id, KnowledgeState.concept_id]
            )
        )
        row = chunk_rows[candidate.chunk_index]
        db.add(
            KnowledgeEvidence(
                user_id=job.user_id,
                concept_id=concept.id,
                document_id=document.id,
                chunk_id=row.id,
                kind=candidate.kind,
                method=candidate.method,
                source_locator=row.locator,
                excerpt=row.snippet,
            )
        )
    await db.flush()
    await refresh_states(db, job.user_id)


def sync_handler(
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    connector_factory: ConnectorFactory = GitHubConnector,
    app_client_factory: Callable[[], GitHubAppClient] | None = None,
) -> Handler:
    async def run(job: Job) -> dict[str, object] | PartialResult:
        async with factory.begin() as db:
            source = await _guard(db, job)
            token = (
                TokenVault(settings.encryption_key).decrypt(source.encrypted_credential)
                if source.encrypted_credential
                else None
            )
            if source.github_connection_id:
                github = app_client_factory() if app_client_factory else GitHubAppClient(settings)
                token = await github.source_token(db, source)
            connector = connector_factory(source.external_ref, token)
            scope = SourceScope(source.external_ref, tuple(source.path_prefixes))
        snapshot = await connector.snapshot(scope)
        paths = {ref.path for ref in snapshot.documents}
        failures: list[dict[str, str]] = []
        stop_code: str | None = None
        processed, unchanged, total_bytes = 0, 0, 0
        seen_blobs: set[str] = set()
        for index, ref in enumerate(snapshot.documents):
            duplicate = ref.blob_sha in seen_blobs
            seen_blobs.add(ref.blob_sha)
            async with factory.begin() as db:
                await _guard(db, job)
                old = await db.scalar(
                    select(SourceDocument).where(
                        SourceDocument.user_id == job.user_id,
                        SourceDocument.source_id == job.source_id,
                        SourceDocument.path == ref.path,
                        SourceDocument.blob_sha == ref.blob_sha,
                        SourceDocument.is_current.is_(True),
                        SourceDocument.deleted_at.is_(None),
                    )
                )
                if old is not None and old.parse_status == (
                    "DUPLICATE"
                    if duplicate
                    else "SKIPPED"
                    if ref.size > file_limit(ref.path)
                    else "PARSED"
                ):
                    unchanged += 1
                    continue
            try:
                if ref.size > file_limit(ref.path) or duplicate:
                    async with factory.begin() as db:
                        await _save_document(
                            db,
                            job,
                            ref,
                            snapshot.revision,
                            None,
                            "DUPLICATE" if duplicate else "SKIPPED",
                            "DUPLICATE_CONTENT" if duplicate else "FILE_TOO_LARGE",
                            paths,
                        )
                        await refresh_states(db, job.user_id)
                else:
                    content = await connector.read_document(scope, ref)
                    total_bytes += len(content)
                    if total_bytes > MAX_BATCH_BYTES:
                        raise Problem(413, "BATCH_BYTE_LIMIT", "批次文本超过上限。")
                    async with factory.begin() as db:
                        await _save_document(
                            db, job, ref, snapshot.revision, content, "PARSED", None, paths
                        )
                    processed += 1
            except Problem as exc:
                if exc.code in {"SOURCE_SYNC_CANCELLED", "BATCH_BYTE_LIMIT"}:
                    raise
                async with factory.begin() as db:
                    await _save_document(
                        db, job, ref, snapshot.revision, None, "FAILED", exc.code, paths
                    )
                failures.append({"path": ref.path, "code": exc.code})
                if exc.code in {"GITHUB_RATE_LIMIT", "GITHUB_ACCESS_DENIED", "CONNECTOR_BUDGET"}:
                    stop_code = exc.code
                    break
            async with factory.begin() as db:
                await _guard(db, job)
                await db.execute(
                    update(Job)
                    .where(Job.id == job.id, Job.user_id == job.user_id)
                    .values(progress=(index + 1) / max(1, len(snapshot.documents)))
                )
        async with factory.begin() as db:
            source = await _guard(db, job)
            old_docs = await db.scalars(
                select(SourceDocument).where(
                    SourceDocument.user_id == job.user_id,
                    SourceDocument.source_id == source.id,
                    SourceDocument.path.not_in(paths),
                    SourceDocument.deleted_at.is_(None),
                )
            )
            for old in old_docs:
                await _retire(db, old)
            source.last_revision, source.last_sync_at = snapshot.revision, datetime.now(UTC)
            await refresh_states(db, job.user_id)
            await after_reindex(db, job)
        result: dict[str, object] = {
            "revision": snapshot.revision,
            "processed": processed,
            "unchanged": unchanged,
            "failures": failures,
            "ignored": snapshot.ignored_count,
        }
        return PartialResult(result, stop_code or "FILES_FAILED") if failures else result

    return run
