"""Private assessments, drafts and separately scoped write permission.

Revision ID: 0007_assessment_artifacts
Revises: 0006_conversation
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.sql.schema import SchemaItem

revision: str = "0007_assessment_artifacts"
down_revision: str | None = "0006_conversation"
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
    op.add_column("knowledge_sources", sa.Column("encrypted_write_credential", sa.Text()))
    op.create_table(
        "assessments",
        *owned(),
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("learning_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("concept_name", sa.String(160), nullable=False),
        sa.Column("question", sa.JSON(), nullable=False),
        sa.Column("answer", sa.String(16)),
        sa.Column("feedback", sa.JSON()),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "evidence_id", sa.Uuid(), sa.ForeignKey("knowledge_evidence.id", ondelete="SET NULL")
        ),
        sa.Column("plan_revision", sa.Integer()),
        sa.UniqueConstraint("user_id", "session_id"),
    )
    op.create_index("ix_assessments_user_id", "assessments", ["user_id"])
    op.create_table(
        "learning_artifacts",
        *owned(),
        sa.Column(
            "assessment_id",
            sa.Uuid(),
            sa.ForeignKey("assessments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("markdown", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("preview", sa.JSON()),
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("jobs.id", ondelete="SET NULL")),
        sa.Column("pr_number", sa.Integer()),
        sa.Column("pr_url", sa.String(2048)),
        sa.Column("merged_at", sa.DateTime(timezone=True)),
        sa.Column("reindexed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("user_id", "assessment_id"),
    )
    op.create_index("ix_learning_artifacts_user_id", "learning_artifacts", ["user_id"])


def downgrade() -> None:
    op.execute("DELETE FROM jobs WHERE kind = 'GITHUB_WRITEBACK'")
    op.execute("DELETE FROM knowledge_evidence WHERE method = 'SOURCE_COMPREHENSION'")
    op.execute("UPDATE knowledge_sources SET write_scope = '[]', version = version + 1")
    op.execute("""
        UPDATE knowledge_states SET level = coalesce(override_level, 'UNKNOWN'),
          confidence = 'LOW', verified_at = NULL, review_due = false,
          evidence_fingerprint = '', version = version + 1
        WHERE NOT EXISTS (SELECT 1 FROM knowledge_evidence e
          WHERE e.user_id = knowledge_states.user_id
            AND e.concept_id = knowledge_states.concept_id AND e.status = 'ACTIVE')
    """)
    op.drop_table("learning_artifacts")
    op.drop_table("assessments")
    op.drop_column("knowledge_sources", "encrypted_write_credential")
