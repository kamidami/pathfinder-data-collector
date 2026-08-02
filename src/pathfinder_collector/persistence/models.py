from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from pathfinder_collector.domain.jobs import utc_now


class Base(DeclarativeBase):
    pass


class UTCDateTime(TypeDecorator[datetime]):
    """Persist UTC and restore timezone information omitted by SQLite."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: object) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: object) -> datetime | None:
        return value.replace(tzinfo=UTC) if value is not None else None


class JobModel(Base):
    __tablename__ = "collection_jobs"
    __table_args__ = (Index("ix_collection_jobs_status", "status"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    country_code: Mapped[str] = mapped_column(String(2))
    entity_type: Mapped[str] = mapped_column(String(30))
    requested_limit: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    error_code: Mapped[str | None] = mapped_column(String(100))
    safe_error_summary: Mapped[str | None] = mapped_column(String(500))


class CandidateModel(Base):
    __tablename__ = "candidate_records"
    __table_args__ = (
        Index("ix_candidates_entity_status", "entity_type", "review_status"),
        Index("ux_candidates_job_source", "job_id", "source_page_id", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("collection_jobs.id", ondelete="CASCADE"))
    source_page_id: Mapped[str | None] = mapped_column(
        ForeignKey("source_pages.id", ondelete="CASCADE")
    )
    entity_type: Mapped[str] = mapped_column(String(30))
    review_status: Mapped[str] = mapped_column(String(30))
    schema_version: Mapped[str] = mapped_column(String(30))
    normalized_data: Mapped[dict[str, Any]] = mapped_column(JSON)
    extraction_version: Mapped[str | None] = mapped_column(String(30))
    last_extracted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    extraction_warnings: Mapped[list[str]] = mapped_column(JSON, default=list)
    reviewer_overrides: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class SourcePageModel(Base):
    __tablename__ = "source_pages"
    __table_args__ = (
        Index("ix_source_pages_normalized_url", "normalized_url"),
        Index("ux_source_pages_job_original_url", "job_id", "original_url", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("collection_jobs.id", ondelete="CASCADE"))
    original_url: Mapped[str] = mapped_column(String(2048))
    normalized_url: Mapped[str] = mapped_column(String(2048))
    source_type: Mapped[str] = mapped_column(String(40))
    official_domain: Mapped[bool] = mapped_column(Boolean)
    fetch_status: Mapped[str] = mapped_column(String(20))
    content_hash: Mapped[str | None] = mapped_column(String(128))
    cached_file_path: Mapped[str | None] = mapped_column(String(500))
    fetched_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    robots_status: Mapped[str] = mapped_column(String(20), default="unavailable")
    http_status: Mapped[int | None] = mapped_column(Integer)
    content_type: Mapped[str | None] = mapped_column(String(100))
    response_bytes: Mapped[int] = mapped_column(Integer, default=0)
    redirect_count: Mapped[int] = mapped_column(Integer, default=0)
    cache_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    error_code: Mapped[str | None] = mapped_column(String(100))
    safe_error_summary: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class CandidateSourceModel(Base):
    __tablename__ = "candidate_sources"
    __table_args__ = (
        Index(
            "ux_candidate_sources_candidate_source", "candidate_id", "source_page_id", unique=True
        ),
        Index("ix_candidate_sources_source", "source_page_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("candidate_records.id", ondelete="CASCADE")
    )
    source_page_id: Mapped[str] = mapped_column(ForeignKey("source_pages.id", ondelete="CASCADE"))
    source_role: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class EvidenceModel(Base):
    __tablename__ = "evidence_records"
    __table_args__ = (Index("ix_evidence_candidate_field", "candidate_id", "field_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("candidate_records.id", ondelete="CASCADE")
    )
    source_page_id: Mapped[str] = mapped_column(ForeignKey("source_pages.id", ondelete="CASCADE"))
    field_name: Mapped[str] = mapped_column(String(100))
    extracted_value: Mapped[str] = mapped_column(Text)
    normalized_value: Mapped[str | None] = mapped_column(Text)
    evidence_locator: Mapped[str | None] = mapped_column(String(500))
    short_evidence_text: Mapped[str | None] = mapped_column(String(500))
    confidence: Mapped[str] = mapped_column(String(20))
    extraction_version: Mapped[str | None] = mapped_column(String(30), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class ConflictModel(Base):
    __tablename__ = "conflict_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("candidate_records.id", ondelete="CASCADE")
    )
    field_name: Mapped[str] = mapped_column(String(100))
    first_evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence_records.id"))
    second_evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence_records.id"))
    resolution_status: Mapped[str] = mapped_column(String(20))
    resolved_value: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    extraction_version: Mapped[str | None] = mapped_column(String(30), index=True)


class CandidateContextModel(Base):
    __tablename__ = "candidate_context_values"
    __table_args__ = (
        Index(
            "ux_candidate_context_field_job",
            "candidate_id",
            "field_name",
            "source_job_id",
            unique=True,
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("candidate_records.id", ondelete="CASCADE")
    )
    field_name: Mapped[str] = mapped_column(String(100))
    value: Mapped[str] = mapped_column(String(2000))
    source_type: Mapped[str] = mapped_column(String(40))
    source_job_id: Mapped[str] = mapped_column(
        ForeignKey("collection_jobs.id", ondelete="RESTRICT")
    )
    effective: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class ContextConflictModel(Base):
    __tablename__ = "context_conflicts"
    __table_args__ = (
        Index(
            "ux_context_conflict_context_evidence",
            "context_value_id",
            "evidence_id",
            unique=True,
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("candidate_records.id", ondelete="CASCADE")
    )
    field_name: Mapped[str] = mapped_column(String(100))
    context_value_id: Mapped[str] = mapped_column(
        ForeignKey("candidate_context_values.id", ondelete="CASCADE")
    )
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence_records.id", ondelete="CASCADE"))
    resolution_status: Mapped[str] = mapped_column(String(20), default="unresolved")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class ConflictResolutionModel(Base):
    __tablename__ = "conflict_resolutions"
    __table_args__ = (
        Index("ix_conflict_resolutions_candidate_time", "candidate_id", "reviewed_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conflict_id: Mapped[str | None] = mapped_column(
        ForeignKey("conflict_records.id", ondelete="SET NULL"), nullable=True
    )
    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("candidate_records.id", ondelete="CASCADE")
    )
    field_name: Mapped[str] = mapped_column(String(100))
    resolution_action: Mapped[str] = mapped_column(String(40))
    selected_value: Mapped[str | None] = mapped_column(Text)
    reviewer_label: Mapped[str] = mapped_column(String(50))
    review_notes: Mapped[str] = mapped_column(String(1000))
    reviewed_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class ExportRunModel(Base):
    __tablename__ = "export_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(30))
    schema_version: Mapped[str] = mapped_column(String(30))
    record_count: Mapped[int] = mapped_column(Integer)
    export_path: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class CandidateReviewModel(Base):
    __tablename__ = "candidate_reviews"
    __table_args__ = (Index("ix_candidate_reviews_candidate_time", "candidate_id", "reviewed_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("candidate_records.id", ondelete="CASCADE")
    )
    reviewer_label: Mapped[str] = mapped_column(String(50))
    decision: Mapped[str] = mapped_column(String(30))
    review_notes: Mapped[str | None] = mapped_column(String(1000))
    reviewed_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    field_overrides: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    acknowledged_warnings: Mapped[bool] = mapped_column(Boolean, default=False)
    original_status: Mapped[str] = mapped_column(String(30))
    resulting_status: Mapped[str] = mapped_column(String(30))


class ExportFileModel(Base):
    __tablename__ = "export_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    export_run_id: Mapped[str] = mapped_column(ForeignKey("export_runs.id", ondelete="CASCADE"))
    filename: Mapped[str] = mapped_column(String(100))
    sha256: Mapped[str] = mapped_column(String(64))
    record_count: Mapped[int] = mapped_column(Integer)


class ExportCandidateModel(Base):
    __tablename__ = "export_candidates"
    __table_args__ = (
        Index("ux_export_candidates_run_candidate", "export_run_id", "candidate_id", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    export_run_id: Mapped[str] = mapped_column(ForeignKey("export_runs.id", ondelete="CASCADE"))
    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("candidate_records.id", ondelete="RESTRICT")
    )


def uuid_string(value: UUID) -> str:
    return str(value)
