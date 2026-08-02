"""Add human review and export history.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    candidate_columns = {item["name"] for item in inspector.get_columns("candidate_records")}
    for column in (
        sa.Column("reviewer_overrides", sa.JSON(), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
    ):
        if column.name not in candidate_columns:
            op.add_column("candidate_records", column)
    op.execute(
        "UPDATE candidate_records SET reviewer_overrides='{}' WHERE reviewer_overrides IS NULL"
    )
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "candidate_reviews" not in tables:
        op.create_table(
            "candidate_reviews",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "candidate_id",
                sa.String(36),
                sa.ForeignKey("candidate_records.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("reviewer_label", sa.String(50), nullable=False),
            sa.Column("decision", sa.String(30), nullable=False),
            sa.Column("review_notes", sa.String(1000), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(), nullable=False),
            sa.Column("field_overrides", sa.JSON(), nullable=False),
            sa.Column("acknowledged_warnings", sa.Boolean(), nullable=False),
            sa.Column("original_status", sa.String(30), nullable=False),
            sa.Column("resulting_status", sa.String(30), nullable=False),
        )
        op.create_index(
            "ix_candidate_reviews_candidate_time",
            "candidate_reviews",
            ["candidate_id", "reviewed_at"],
        )
    if "export_files" not in tables:
        op.create_table(
            "export_files",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "export_run_id",
                sa.String(36),
                sa.ForeignKey("export_runs.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("filename", sa.String(100), nullable=False),
            sa.Column("sha256", sa.String(64), nullable=False),
            sa.Column("record_count", sa.Integer(), nullable=False),
        )
    if "export_candidates" not in tables:
        op.create_table(
            "export_candidates",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "export_run_id",
                sa.String(36),
                sa.ForeignKey("export_runs.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "candidate_id",
                sa.String(36),
                sa.ForeignKey("candidate_records.id", ondelete="RESTRICT"),
                nullable=False,
            ),
        )
        op.create_index(
            "ux_export_candidates_run_candidate",
            "export_candidates",
            ["export_run_id", "candidate_id"],
            unique=True,
        )


def downgrade() -> None:
    op.drop_table("export_candidates")
    op.drop_table("export_files")
    op.drop_table("candidate_reviews")
    op.drop_column("candidate_records", "approved_at")
    op.drop_column("candidate_records", "reviewer_overrides")
