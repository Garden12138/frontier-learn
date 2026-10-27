"""Explicit model processing preferences, default denied.

Revision ID: 0008_ownership
Revises: 0007_assessment_artifacts
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_ownership"
down_revision: str | None = "0007_assessment_artifacts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "cloud_processing_allowed", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column(
        "users", sa.Column("settings_version", sa.Integer(), nullable=False, server_default="1")
    )
    op.alter_column("users", "cloud_processing_allowed", server_default=None)
    op.alter_column("users", "settings_version", server_default=None)


def downgrade() -> None:
    op.drop_column("users", "settings_version")
    op.drop_column("users", "cloud_processing_allowed")
