from datetime import UTC, date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    """Independent identity; a GitHub connection is optional."""

    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    identity: Mapped[str] = mapped_column(String(320), unique=True)
    cloud_processing_allowed: Mapped[bool] = mapped_column(default=False)
    settings_version: Mapped[int] = mapped_column(default=1)
    github_auth_version: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def public_identity(self) -> str:
        return self.identity.removeprefix("account:")


class OwnedEntity(Base):
    __abstract__ = True

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuthSession(OwnedEntity):
    __tablename__ = "auth_sessions"

    token_digest: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    auth_method: Mapped[str] = mapped_column(String(16), default="DEVELOPMENT")


class PasswordCredential(OwnedEntity):
    __tablename__ = "password_credentials"
    __table_args__ = (UniqueConstraint("user_id"),)
    password_hash: Mapped[str] = mapped_column(Text)
    recovery_digest: Mapped[str] = mapped_column(String(64))


class AuthRateLimit(Base):
    __tablename__ = "auth_rate_limits"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    window: Mapped[int] = mapped_column(primary_key=True)
    attempts: Mapped[int] = mapped_column(default=0)


class ModelBudget(Base):
    __tablename__ = "model_budgets"
    scope: Mapped[str] = mapped_column(String(64), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    calls: Mapped[int] = mapped_column(default=0)
    reserved_tokens: Mapped[int] = mapped_column(default=0)


class ModelCall(OwnedEntity):
    __tablename__ = "model_calls"
    __table_args__ = (UniqueConstraint("job_id", "attempt"),)
    job_id: Mapped[UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    attempt: Mapped[int] = mapped_column()
    reserved_tokens: Mapped[int] = mapped_column()
    input_tokens: Mapped[int | None] = mapped_column()
    output_tokens: Mapped[int | None] = mapped_column()


class GitHubConnection(OwnedEntity):
    __tablename__ = "github_connections"
    __table_args__ = (UniqueConstraint("user_id"),)
    github_user_id: Mapped[int] = mapped_column(BigInteger)
    login: Mapped[str] = mapped_column(String(100))
    encrypted_token: Mapped[str | None] = mapped_column(Text)
    encrypted_refresh: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), default="CONNECTED")


class GitHubOAuthState(OwnedEntity):
    __tablename__ = "github_oauth_states"
    auth_version: Mapped[int] = mapped_column()
    state_digest: Mapped[str] = mapped_column(String(64), unique=True)
    session_digest: Mapped[str] = mapped_column(String(64))
    browser_digest: Mapped[str] = mapped_column(String(64))
    encrypted_verifier: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class KnowledgeSource(OwnedEntity):
    __tablename__ = "knowledge_sources"
    __table_args__ = (UniqueConstraint("user_id", "provider", "external_ref"),)

    provider: Mapped[str] = mapped_column(String(32))
    external_ref: Mapped[str] = mapped_column(String(256))
    read_scope: Mapped[list[str]] = mapped_column(JSON, default=list)
    path_prefixes: Mapped[list[str]] = mapped_column(JSON, default=list)
    write_scope: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), default="CONNECTED")
    encrypted_credential: Mapped[str | None] = mapped_column(Text)
    encrypted_write_credential: Mapped[str | None] = mapped_column(Text)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_revision: Mapped[str | None] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(default=1)
    active_job_id: Mapped[UUID | None] = mapped_column()
    github_connection_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("github_connections.id", ondelete="SET NULL")
    )
    github_installation_id: Mapped[int | None] = mapped_column(BigInteger)
    github_repository_id: Mapped[int | None] = mapped_column(BigInteger)


class SourceDocument(OwnedEntity):
    __tablename__ = "source_documents"
    __table_args__ = (UniqueConstraint("source_id", "path", "blob_sha"),)

    source_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_sources.id", ondelete="CASCADE"), index=True
    )
    path: Mapped[str] = mapped_column(String(1000))
    revision: Mapped[str] = mapped_column(String(40))
    blob_sha: Mapped[str] = mapped_column(String(40))
    content_hash: Mapped[str | None] = mapped_column(String(64))
    content_text: Mapped[str | None] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column()
    parse_status: Mapped[str] = mapped_column(String(32))
    error_code: Mapped[str | None] = mapped_column(String(64))
    is_current: Mapped[bool] = mapped_column(default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    renamed_from: Mapped[str | None] = mapped_column(String(1000))


class SourceChunk(OwnedEntity):
    __tablename__ = "source_chunks"

    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_documents.id", ondelete="CASCADE"), index=True
    )
    locator: Mapped[dict[str, object]] = mapped_column(JSON)
    text_checksum: Mapped[str] = mapped_column(String(64))
    snippet: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(String(16))


class KnowledgeConcept(Base):
    __tablename__ = "knowledge_concepts"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    # Only normalized concept labels are shared; source bodies and learner state are private.
    canonical_name: Mapped[str] = mapped_column(String(160), unique=True)


class KnowledgeEvidence(OwnedEntity):
    __tablename__ = "knowledge_evidence"

    concept_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_concepts.id"), index=True)
    document_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("source_documents.id", ondelete="CASCADE"), index=True
    )
    chunk_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("source_chunks.id", ondelete="CASCADE")
    )
    assessment_id: Mapped[UUID | None] = mapped_column()
    kind: Mapped[str] = mapped_column(String(32))
    polarity: Mapped[str] = mapped_column(String(16), default="NEUTRAL")
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    reliability: Mapped[str] = mapped_column(String(16), default="LOW")
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE", index=True)
    method: Mapped[str] = mapped_column(String(64), default="SOURCE_TEXT")
    source_locator: Mapped[dict[str, object]] = mapped_column(JSON)
    excerpt: Mapped[str] = mapped_column(Text)


class Assessment(OwnedEntity):
    __tablename__ = "assessments"
    __table_args__ = (UniqueConstraint("user_id", "session_id"),)

    session_id: Mapped[UUID] = mapped_column(ForeignKey("learning_sessions.id", ondelete="CASCADE"))
    concept_name: Mapped[str] = mapped_column(String(160))
    question: Mapped[dict[str, object]] = mapped_column(JSON)
    answer: Mapped[str | None] = mapped_column(String(16))
    feedback: Mapped[dict[str, object] | None] = mapped_column(JSON)
    version: Mapped[int] = mapped_column(default=1)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    evidence_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("knowledge_evidence.id", ondelete="SET NULL")
    )
    plan_revision: Mapped[int | None] = mapped_column()


class LearningArtifact(OwnedEntity):
    __tablename__ = "learning_artifacts"
    __table_args__ = (UniqueConstraint("user_id", "assessment_id"),)

    assessment_id: Mapped[UUID] = mapped_column(ForeignKey("assessments.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))
    markdown: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(default=1)
    preview: Mapped[dict[str, object] | None] = mapped_column(JSON)
    job_id: Mapped[UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    pr_number: Mapped[int | None] = mapped_column()
    pr_url: Mapped[str | None] = mapped_column(String(2048))
    merged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reindexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KnowledgeState(OwnedEntity):
    __tablename__ = "knowledge_states"
    __table_args__ = (UniqueConstraint("user_id", "concept_id"),)

    concept_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_concepts.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    level: Mapped[str] = mapped_column(String(32), default="UNKNOWN")
    confidence: Mapped[str] = mapped_column(String(16), default="LOW")
    review_due: Mapped[bool] = mapped_column(default=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    policy_version: Mapped[str] = mapped_column(String(16), default="1")
    evidence_fingerprint: Mapped[str] = mapped_column(String(64), default="")
    version: Mapped[int] = mapped_column(default=1)
    override_level: Mapped[str | None] = mapped_column(String(32))
    override_reason: Mapped[str | None] = mapped_column(Text)


class Job(OwnedEntity):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("user_id", "kind", "idempotency_key"),
        CheckConstraint("attempt_count >= 0 AND attempt_count <= max_attempts"),
        CheckConstraint("max_attempts BETWEEN 1 AND 3"),
        CheckConstraint("budget_units BETWEEN 1 AND 1000"),
        CheckConstraint("spent_units >= 0 AND spent_units <= budget_units"),
        CheckConstraint("timeout_seconds BETWEEN 1 AND 120"),
    )

    source_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("knowledge_sources.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(String(32))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="PENDING", index=True)
    attempt_count: Mapped[int] = mapped_column(default=0)
    max_attempts: Mapped[int] = mapped_column(default=3)
    budget_units: Mapped[int] = mapped_column(default=20)
    spent_units: Mapped[int] = mapped_column(default=0)
    timeout_seconds: Mapped[int] = mapped_column(default=60)
    progress: Mapped[float] = mapped_column(default=0.0)
    error_code: Mapped[str | None] = mapped_column(String(64))
    result: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lease_id: Mapped[UUID | None] = mapped_column()
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditEvent(OwnedEntity):
    __tablename__ = "audit_events"

    operation: Mapped[str] = mapped_column(String(64))
    object_type: Mapped[str] = mapped_column(String(32))
    object_id: Mapped[str] = mapped_column(String(64))
    # Summary codes only: never source text, credentials or exception messages.
    summary_code: Mapped[str] = mapped_column(String(64))


class LearningGoal(OwnedEntity):
    __tablename__ = "learning_goals"
    __table_args__ = (
        CheckConstraint("minutes_per_day BETWEEN 5 AND 240"),
        UniqueConstraint("user_id", "creation_key"),
    )

    creation_key: Mapped[str] = mapped_column(String(128))
    creation_hash: Mapped[str] = mapped_column(String(64))

    title: Mapped[str] = mapped_column(String(500))
    minutes_per_day: Mapped[int] = mapped_column()
    priorities: Mapped[list[str]] = mapped_column(JSON, default=list)
    prerequisite_edges: Mapped[list[dict[str, str]]] = mapped_column(JSON, default=list)
    self_report: Mapped[str] = mapped_column(String(32), default="UNKNOWN")
    self_report_reason: Mapped[str] = mapped_column(String(1000), default="")
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    version: Mapped[int] = mapped_column(default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class LearningPlan(OwnedEntity):
    __tablename__ = "learning_plans"
    __table_args__ = (UniqueConstraint("goal_id"),)

    goal_id: Mapped[UUID] = mapped_column(
        ForeignKey("learning_goals.id", ondelete="CASCADE"), index=True
    )
    active_revision: Mapped[int] = mapped_column(default=0)


class LearningPlanRevision(OwnedEntity):
    __tablename__ = "learning_plan_revisions"
    __table_args__ = (UniqueConstraint("plan_id", "revision_no"),)

    plan_id: Mapped[UUID] = mapped_column(
        ForeignKey("learning_plans.id", ondelete="CASCADE"), index=True
    )
    revision_no: Mapped[int] = mapped_column()
    rationale: Mapped[str] = mapped_column(String(1200))
    document: Mapped[dict[str, object]] = mapped_column(JSON)


class LearningTask(OwnedEntity):
    """Latest projection; immutable historical task snapshots live in plan revisions."""

    __tablename__ = "learning_tasks"

    plan_id: Mapped[UUID] = mapped_column(
        ForeignKey("learning_plans.id", ondelete="CASCADE"), index=True
    )
    revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("learning_plan_revisions.id", ondelete="CASCADE")
    )
    title: Mapped[str] = mapped_column(String(700))
    kind: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32))
    estimated_minutes: Mapped[int] = mapped_column()
    is_current: Mapped[bool] = mapped_column(default=True)


class TaskCompletion(OwnedEntity):
    __tablename__ = "task_completions"
    __table_args__ = (UniqueConstraint("user_id", "task_id", "local_day"),)

    plan_id: Mapped[UUID] = mapped_column(
        ForeignKey("learning_plans.id", ondelete="CASCADE"), index=True
    )
    task_id: Mapped[UUID] = mapped_column(ForeignKey("learning_tasks.id", ondelete="CASCADE"))
    local_day: Mapped[date] = mapped_column(Date)
    timezone: Mapped[str] = mapped_column(String(64))
    minutes: Mapped[int] = mapped_column()


class LearningSession(OwnedEntity):
    __tablename__ = "learning_sessions"
    __table_args__ = (UniqueConstraint("user_id", "creation_key"),)

    creation_key: Mapped[str] = mapped_column(String(128))
    creation_hash: Mapped[str] = mapped_column(String(64))
    page: Mapped[dict[str, object]] = mapped_column(JSON)
    content_hash: Mapped[str] = mapped_column(String(64))
    goal_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("learning_goals.id", ondelete="SET NULL")
    )
    task_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("learning_tasks.id", ondelete="SET NULL")
    )
    version: Mapped[int] = mapped_column(default=1)


class TutorTurn(OwnedEntity):
    __tablename__ = "tutor_turns"
    __table_args__ = (
        UniqueConstraint("session_id", "request_key"),
        UniqueConstraint("session_id", "turn_no"),
        CheckConstraint("turn_no BETWEEN 1 AND 20"),
    )

    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("learning_sessions.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    request_key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    turn_no: Mapped[int] = mapped_column()
    question: Mapped[str] = mapped_column(String(1000))
    cloud_processing_allowed: Mapped[bool] = mapped_column(default=False)
    mode: Mapped[str] = mapped_column(String(16))
    selection: Mapped[dict[str, object] | None] = mapped_column(JSON)
    guide: Mapped[dict[str, object] | None] = mapped_column(JSON)


class ConversationImport(OwnedEntity):
    __tablename__ = "conversation_imports"
    __table_args__ = (UniqueConstraint("user_id", "creation_key"),)

    creation_key: Mapped[str] = mapped_column(String(128))
    creation_hash: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(16))
    source_url: Mapped[str | None] = mapped_column(String(2048))
    pasted_text: Mapped[str | None] = mapped_column(Text)
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    document: Mapped[dict[str, object] | None] = mapped_column(JSON)
    candidates: Mapped[list[dict[str, object]]] = mapped_column(JSON, default=list)
    version: Mapped[int] = mapped_column(default=1)
