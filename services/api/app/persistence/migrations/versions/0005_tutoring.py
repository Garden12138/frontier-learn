"""User-owned page snapshots and bounded tutor turns.

Revision ID: 0005_tutoring
Revises: 0004_planning
"""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from alembic import op

revision: str = "0005_tutoring"
down_revision: str | None = "0004_planning"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def owned_columns() -> tuple[sa.Column[UUID], sa.Column[UUID], sa.Column[datetime]]:
    return (
        sa.Column("id", sa.Uuid(), nullable=False, primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def upgrade() -> None:
    op.create_table(
        "learning_sessions",
        *owned_columns(),
        sa.Column("creation_key", sa.String(128), nullable=False),
        sa.Column("creation_hash", sa.String(64), nullable=False),
        sa.Column("page", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("goal_id", sa.Uuid(), sa.ForeignKey("learning_goals.id", ondelete="SET NULL")),
        sa.Column("task_id", sa.Uuid(), sa.ForeignKey("learning_tasks.id", ondelete="SET NULL")),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.UniqueConstraint("user_id", "creation_key"),
    )
    op.create_index("ix_learning_sessions_user_id", "learning_sessions", ["user_id"])
    op.create_table(
        "tutor_turns",
        *owned_columns(),
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("learning_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "job_id", sa.Uuid(), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("request_key", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("turn_no", sa.Integer(), nullable=False),
        sa.Column("question", sa.String(1000), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("selection", sa.JSON()),
        sa.Column("guide", sa.JSON()),
        sa.UniqueConstraint("session_id", "request_key"),
        sa.UniqueConstraint("session_id", "turn_no"),
        sa.CheckConstraint("turn_no BETWEEN 1 AND 20"),
    )
    op.create_index("ix_tutor_turns_user_id", "tutor_turns", ["user_id"])
    op.create_index("ix_tutor_turns_session_id", "tutor_turns", ["session_id"])


def downgrade() -> None:
    # Job payloads hold IDs only; remove the orphaned task metadata during explicit rollback.
    op.execute("DELETE FROM jobs WHERE kind = 'TUTOR_GUIDE'")
    op.drop_table("tutor_turns")
    op.drop_table("learning_sessions")
