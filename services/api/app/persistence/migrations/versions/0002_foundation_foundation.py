"""foundation

Revision ID: 0002_foundation
Revises: 0001_users
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_foundation"
down_revision: str | None = "0001_users"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Reviewed against OwnedEntity boundaries and database check constraints.
    op.create_table(
        "audit_events",
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column("object_type", sa.String(length=32), nullable=False),
        sa.Column("object_id", sa.String(length=64), nullable=False),
        sa.Column("summary_code", sa.String(length=64), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_audit_events_user_id"), "audit_events", ["user_id"], unique=False)
    op.create_table(
        "auth_sessions",
        sa.Column("token_digest", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_digest"),
    )
    op.create_index(op.f("ix_auth_sessions_user_id"), "auth_sessions", ["user_id"], unique=False)
    op.create_table(
        "knowledge_sources",
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("external_ref", sa.String(length=256), nullable=False),
        sa.Column("read_scope", sa.JSON(), nullable=False),
        sa.Column("write_scope", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("encrypted_credential", sa.Text(), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_revision", sa.String(length=64), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "provider", "external_ref"),
    )
    op.create_index(
        op.f("ix_knowledge_sources_user_id"), "knowledge_sources", ["user_id"], unique=False
    )
    op.create_table(
        "jobs",
        sa.Column("source_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("budget_units", sa.Integer(), nullable=False),
        sa.Column("spent_units", sa.Integer(), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("progress", sa.Float(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_id", sa.Uuid(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("attempt_count >= 0 AND attempt_count <= max_attempts"),
        sa.CheckConstraint("budget_units BETWEEN 1 AND 1000"),
        sa.CheckConstraint("max_attempts BETWEEN 1 AND 3"),
        sa.CheckConstraint("spent_units >= 0 AND spent_units <= budget_units"),
        sa.CheckConstraint("timeout_seconds BETWEEN 1 AND 120"),
        sa.ForeignKeyConstraint(["source_id"], ["knowledge_sources.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "kind", "idempotency_key"),
    )
    op.create_index(op.f("ix_jobs_status"), "jobs", ["status"], unique=False)
    op.create_index(op.f("ix_jobs_user_id"), "jobs", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_jobs_user_id"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_status"), table_name="jobs")
    op.drop_table("jobs")
    op.drop_index(op.f("ix_knowledge_sources_user_id"), table_name="knowledge_sources")
    op.drop_table("knowledge_sources")
    op.drop_index(op.f("ix_auth_sessions_user_id"), table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_index(op.f("ix_audit_events_user_id"), table_name="audit_events")
    op.drop_table("audit_events")
