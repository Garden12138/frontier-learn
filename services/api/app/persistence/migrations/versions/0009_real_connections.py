"""Independent password identities, model budgets, and optional GitHub App links.

Revision ID: 0009_real_connections
Revises: 0008_ownership
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.sql.schema import SchemaItem

revision: str = "0009_real_connections"
down_revision: str | None = "0008_ownership"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def owned() -> list[SchemaItem]:
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("github_auth_version", sa.Integer(), nullable=False, server_default="0")
    )
    op.alter_column("users", "github_auth_version", server_default=None)
    op.add_column(
        "tutor_turns",
        sa.Column(
            "cloud_processing_allowed", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.alter_column("tutor_turns", "cloud_processing_allowed", server_default=None)
    op.add_column(
        "auth_sessions",
        sa.Column("auth_method", sa.String(16), nullable=False, server_default="DEVELOPMENT"),
    )
    op.alter_column("auth_sessions", "auth_method", server_default=None)
    op.create_table(
        "password_credentials",
        *owned(),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("recovery_digest", sa.String(64), nullable=False),
        sa.UniqueConstraint("user_id"),
    )
    op.create_table(
        "auth_rate_limits",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("window", sa.Integer(), primary_key=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
    )
    op.create_table(
        "model_budgets",
        sa.Column("scope", sa.String(64), primary_key=True),
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("calls", sa.Integer(), nullable=False),
        sa.Column("reserved_tokens", sa.Integer(), nullable=False),
    )
    op.create_table(
        "model_calls",
        *owned(),
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("jobs.id", ondelete="SET NULL")),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("reserved_tokens", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer()),
        sa.Column("output_tokens", sa.Integer()),
        sa.UniqueConstraint("job_id", "attempt"),
    )
    op.create_table(
        "github_connections",
        *owned(),
        sa.Column("github_user_id", sa.BigInteger(), nullable=False),
        sa.Column("login", sa.String(100), nullable=False),
        sa.Column("encrypted_token", sa.Text()),
        sa.Column("encrypted_refresh", sa.Text()),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.UniqueConstraint("user_id"),
    )
    op.create_table(
        "github_oauth_states",
        *owned(),
        sa.Column("auth_version", sa.Integer(), nullable=False),
        sa.Column("state_digest", sa.String(64), nullable=False, unique=True),
        sa.Column("session_digest", sa.String(64), nullable=False),
        sa.Column("browser_digest", sa.String(64), nullable=False),
        sa.Column("encrypted_verifier", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    for name in (
        "password_credentials",
        "model_calls",
        "github_connections",
        "github_oauth_states",
    ):
        op.create_index(f"ix_{name}_user_id", name, ["user_id"])
    op.add_column(
        "knowledge_sources",
        sa.Column(
            "github_connection_id",
            sa.Uuid(),
            sa.ForeignKey("github_connections.id", ondelete="SET NULL"),
        ),
    )
    op.add_column("knowledge_sources", sa.Column("github_installation_id", sa.BigInteger()))
    op.add_column("knowledge_sources", sa.Column("github_repository_id", sa.BigInteger()))


def downgrade() -> None:
    # Formal login is disabled after rollback; never enable Mock with real private data.
    op.execute("DELETE FROM auth_sessions WHERE auth_method <> 'DEVELOPMENT'")
    op.execute(
        "UPDATE knowledge_sources SET status = 'DISCONNECTED', write_scope = '[]', "
        "version = version + 1 WHERE github_connection_id IS NOT NULL"
    )
    for column in ("github_repository_id", "github_installation_id", "github_connection_id"):
        op.drop_column("knowledge_sources", column)
    for name in (
        "github_oauth_states",
        "github_connections",
        "model_calls",
        "model_budgets",
        "auth_rate_limits",
        "password_credentials",
    ):
        op.drop_table(name)
    op.drop_column("auth_sessions", "auth_method")
    op.drop_column("tutor_turns", "cloud_processing_allowed")
    op.drop_column("users", "github_auth_version")
