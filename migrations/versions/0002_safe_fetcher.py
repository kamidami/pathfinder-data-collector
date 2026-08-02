"""Add safe fetch metadata to source pages.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing_columns = {item["name"] for item in inspector.get_columns("source_pages")}
    additions = (
        sa.Column("robots_status", sa.String(20), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("content_type", sa.String(100), nullable=True),
        sa.Column("response_bytes", sa.Integer(), nullable=True),
        sa.Column("redirect_count", sa.Integer(), nullable=True),
        sa.Column("cache_expires_at", sa.DateTime(), nullable=True),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("safe_error_summary", sa.String(500), nullable=True),
    )
    for column in additions:
        if column.name not in existing_columns:
            op.add_column("source_pages", column)
    op.execute(
        "UPDATE source_pages SET robots_status='unavailable', response_bytes=0, redirect_count=0"
    )
    existing_indexes = {item["name"] for item in inspector.get_indexes("source_pages")}
    if "ux_source_pages_job_original_url" not in existing_indexes:
        op.create_index(
            "ux_source_pages_job_original_url",
            "source_pages",
            ["job_id", "original_url"],
            unique=True,
        )


def downgrade() -> None:
    op.drop_index("ux_source_pages_job_original_url", table_name="source_pages")
    for column in (
        "safe_error_summary",
        "error_code",
        "cache_expires_at",
        "redirect_count",
        "response_bytes",
        "content_type",
        "http_status",
        "robots_status",
    ):
        op.drop_column("source_pages", column)
