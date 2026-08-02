"""Add deterministic programme extraction metadata.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def _add_missing(table: str, columns: tuple[sa.Column, ...]) -> None:
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}
    for column in columns:
        if column.name not in existing:
            op.add_column(table, column)


def upgrade() -> None:
    _add_missing(
        "candidate_records",
        (
            sa.Column("source_page_id", sa.String(36), nullable=True),
            sa.Column("extraction_version", sa.String(30), nullable=True),
            sa.Column("last_extracted_at", sa.DateTime(), nullable=True),
            sa.Column("extraction_warnings", sa.JSON(), nullable=True),
        ),
    )
    _add_missing(
        "evidence_records",
        (
            sa.Column("normalized_value", sa.Text(), nullable=True),
            sa.Column("extraction_version", sa.String(30), nullable=True),
        ),
    )
    _add_missing(
        "conflict_records",
        (sa.Column("extraction_version", sa.String(30), nullable=True),),
    )
    op.execute(
        "UPDATE candidate_records SET extraction_warnings='[]' WHERE extraction_warnings IS NULL"
    )
    inspector = sa.inspect(op.get_bind())
    foreign_keys = inspector.get_foreign_keys("candidate_records")
    if not any(key.get("constrained_columns") == ["source_page_id"] for key in foreign_keys):
        with op.batch_alter_table("candidate_records") as batch:
            batch.create_foreign_key(
                "fk_candidates_source_page",
                "source_pages",
                ["source_page_id"],
                ["id"],
                ondelete="CASCADE",
            )
        inspector = sa.inspect(op.get_bind())
    candidate_indexes = {index["name"] for index in inspector.get_indexes("candidate_records")}
    if "ux_candidates_job_source" not in candidate_indexes:
        op.create_index(
            "ux_candidates_job_source",
            "candidate_records",
            ["job_id", "source_page_id"],
            unique=True,
        )
    for table in ("evidence_records", "conflict_records"):
        name = f"ix_{table}_extraction_version"
        indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table)}
        if name not in indexes:
            op.create_index(name, table, ["extraction_version"])


def downgrade() -> None:
    op.drop_index("ix_conflict_records_extraction_version", table_name="conflict_records")
    op.drop_index("ix_evidence_records_extraction_version", table_name="evidence_records")
    op.drop_index("ux_candidates_job_source", table_name="candidate_records")
    for table, columns in (
        ("conflict_records", ("extraction_version",)),
        ("evidence_records", ("extraction_version", "normalized_value")),
        (
            "candidate_records",
            ("extraction_warnings", "last_extracted_at", "extraction_version", "source_page_id"),
        ),
    ):
        for column in columns:
            op.drop_column(table, column)
