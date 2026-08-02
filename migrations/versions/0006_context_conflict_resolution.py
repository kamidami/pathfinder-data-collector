"""add operator context and conflict resolution audit

Revision ID: 0006
Revises: 0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "candidate_context_values" not in tables:
        op.create_table(
            "candidate_context_values",
            sa.Column("id", sa.String(36), nullable=False),
            sa.Column("candidate_id", sa.String(36), nullable=False),
            sa.Column("field_name", sa.String(100), nullable=False),
            sa.Column("value", sa.String(2000), nullable=False),
            sa.Column("source_type", sa.String(40), nullable=False),
            sa.Column("source_job_id", sa.String(36), nullable=False),
            sa.Column("effective", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["candidate_id"], ["candidate_records.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["source_job_id"], ["collection_jobs.id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ux_candidate_context_field_job",
            "candidate_context_values",
            ["candidate_id", "field_name", "source_job_id"],
            unique=True,
        )
    if "context_conflicts" not in tables:
        op.create_table(
            "context_conflicts",
            sa.Column("id", sa.String(36), nullable=False),
            sa.Column("candidate_id", sa.String(36), nullable=False),
            sa.Column("field_name", sa.String(100), nullable=False),
            sa.Column("context_value_id", sa.String(36), nullable=False),
            sa.Column("evidence_id", sa.String(36), nullable=False),
            sa.Column("resolution_status", sa.String(20), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["candidate_id"], ["candidate_records.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["context_value_id"], ["candidate_context_values.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(["evidence_id"], ["evidence_records.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ux_context_conflict_context_evidence",
            "context_conflicts",
            ["context_value_id", "evidence_id"],
            unique=True,
        )
    if "conflict_resolutions" not in tables:
        op.create_table(
            "conflict_resolutions",
            sa.Column("id", sa.String(36), nullable=False),
            sa.Column("conflict_id", sa.String(36), nullable=True),
            sa.Column("candidate_id", sa.String(36), nullable=False),
            sa.Column("field_name", sa.String(100), nullable=False),
            sa.Column("resolution_action", sa.String(40), nullable=False),
            sa.Column("selected_value", sa.Text(), nullable=True),
            sa.Column("reviewer_label", sa.String(50), nullable=False),
            sa.Column("review_notes", sa.String(1000), nullable=False),
            sa.Column("reviewed_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["conflict_id"], ["conflict_records.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["candidate_id"], ["candidate_records.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_conflict_resolutions_candidate_time",
            "conflict_resolutions",
            ["candidate_id", "reviewed_at"],
            unique=False,
        )


def downgrade() -> None:
    op.drop_table("conflict_resolutions")
    op.drop_table("context_conflicts")
    op.drop_table("candidate_context_values")
