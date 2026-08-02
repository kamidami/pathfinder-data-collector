"""associate candidates with primary and supporting sources

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "candidate_sources" not in inspector.get_table_names():
        op.create_table(
            "candidate_sources",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("candidate_id", sa.String(length=36), nullable=False),
            sa.Column("source_page_id", sa.String(length=36), nullable=False),
            sa.Column("source_role", sa.String(length=20), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["candidate_id"], ["candidate_records.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["source_page_id"], ["source_pages.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ux_candidate_sources_candidate_source",
            "candidate_sources",
            ["candidate_id", "source_page_id"],
            unique=True,
        )
        op.create_index(
            "ix_candidate_sources_source", "candidate_sources", ["source_page_id"], unique=False
        )
    op.execute(
        "INSERT INTO candidate_sources (candidate_id, source_page_id, source_role, created_at) "
        "SELECT id, source_page_id, 'primary', created_at FROM candidate_records "
        "WHERE source_page_id IS NOT NULL AND NOT EXISTS ("
        "SELECT 1 FROM candidate_sources cs WHERE cs.candidate_id = candidate_records.id "
        "AND cs.source_page_id = candidate_records.source_page_id)"
    )


def downgrade() -> None:
    op.drop_index("ix_candidate_sources_source", table_name="candidate_sources")
    op.drop_index("ux_candidate_sources_candidate_source", table_name="candidate_sources")
    op.drop_table("candidate_sources")
