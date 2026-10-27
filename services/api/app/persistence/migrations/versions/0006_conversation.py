"""Private conversation imports and candidate decisions.

Revision ID: 0006_conversation
Revises: 0005_tutoring
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_conversation"
down_revision: str | None = "0005_tutoring"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversation_imports",
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
        sa.Column("creation_key", sa.String(128), nullable=False),
        sa.Column("creation_hash", sa.String(64), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("source_url", sa.String(2048)),
        sa.Column("pasted_text", sa.Text()),
        sa.Column(
            "job_id", sa.Uuid(), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("document", sa.JSON()),
        sa.Column("candidates", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.UniqueConstraint("user_id", "creation_key"),
    )
    op.create_index("ix_conversation_imports_user_id", "conversation_imports", ["user_id"])


def downgrade() -> None:
    # Phase 5's strict task schema cannot read the new JSON field, even when it is null.
    # Keep each task and revision, removing only this feature's source metadata in order.
    op.execute("""
        UPDATE learning_plan_revisions
        SET document = jsonb_set(document::jsonb, '{tasks}', (
            SELECT coalesce(jsonb_agg(item - 'conversation_ref' ORDER BY ordinal_no), '[]'::jsonb)
            FROM jsonb_array_elements(document::jsonb -> 'tasks')
                 WITH ORDINALITY AS entries(item, ordinal_no)
        ))::json
        WHERE jsonb_typeof(document::jsonb -> 'tasks') = 'array'
    """)
    op.execute("DELETE FROM jobs WHERE kind = 'CONVERSATION_IMPORT'")
    op.drop_table("conversation_imports")
