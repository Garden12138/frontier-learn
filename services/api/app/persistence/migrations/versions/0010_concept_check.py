"""Concept question state; existing assessments remain local source-boundary checks."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_concept_check"
down_revision: str | None = "0009_real_connections"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("assessments", sa.Column("grading", sa.JSON(), nullable=True))
    op.add_column("assessments", sa.Column("question_job_id", sa.Uuid(), nullable=True))
    op.add_column(
        "assessments",
        sa.Column(
            "cloud_processing_allowed", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.alter_column("assessments", "cloud_processing_allowed", server_default=None)
    op.create_foreign_key(
        "fk_assessment_question_job",
        "assessments",
        "jobs",
        ["question_job_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.execute(
        "UPDATE jobs SET status='CANCELLED', lease_id=NULL, finished_at=now() "
        "WHERE kind='ASSESSMENT_QUESTION' AND status IN ('PENDING','RUNNING')"
    )
    # New questions cannot be interpreted by 0009's fixed answer rule. Remove only new concept
    # checks and their derived records, preserving old boundary questions and independent evidence.
    op.execute(
        "CREATE TEMP TABLE concept_rollback_owners ON COMMIT DROP AS "
        "SELECT DISTINCT user_id, concept_id FROM knowledge_evidence "
        "WHERE method='MODEL_CONCEPT_CHECK'"
    )
    op.execute(
        "UPDATE knowledge_states s SET evidence_fingerprint='', version=version+1 "
        "WHERE EXISTS (SELECT 1 FROM concept_rollback_owners r "
        "WHERE r.user_id=s.user_id AND r.concept_id=s.concept_id)"
    )
    op.execute(
        "DELETE FROM knowledge_evidence WHERE assessment_id IN "
        "(SELECT id FROM assessments WHERE question->>'scope'='CONCEPT_CHECK')"
    )
    op.execute("DELETE FROM assessments WHERE question->>'scope'='CONCEPT_CHECK'")
    op.execute(
        "UPDATE knowledge_states s SET level=COALESCE(override_level, 'UNKNOWN'), "
        "confidence='LOW', verified_at=NULL WHERE EXISTS "
        "(SELECT 1 FROM concept_rollback_owners r WHERE r.user_id=s.user_id "
        "AND r.concept_id=s.concept_id) AND NOT EXISTS "
        "(SELECT 1 FROM knowledge_evidence e WHERE e.user_id=s.user_id "
        "AND e.concept_id=s.concept_id AND e.status='ACTIVE' AND e.kind<>'AI_CLAIM')"
    )
    op.drop_constraint("fk_assessment_question_job", "assessments", type_="foreignkey")
    op.drop_column("assessments", "cloud_processing_allowed")
    op.drop_column("assessments", "question_job_id")
    op.drop_column("assessments", "grading")
    op.execute("DELETE FROM jobs WHERE kind='ASSESSMENT_QUESTION'")
