from datetime import datetime
from uuid import UUID, uuid4

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field

from pathfinder_collector.domain.jobs import utc_now
from pathfinder_collector.enums import (
    ConfidenceLevel,
    FetchStatus,
    ResolutionStatus,
    RobotsStatus,
    SourceType,
)


class SourcePage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    job_id: UUID
    original_url: AnyHttpUrl
    normalized_url: AnyHttpUrl
    source_type: SourceType
    official_domain: bool
    fetch_status: FetchStatus = FetchStatus.PENDING
    content_hash: str | None = Field(default=None, max_length=128)
    cached_file_path: str | None = Field(default=None, max_length=500)
    fetched_at: datetime | None = None
    robots_status: RobotsStatus = RobotsStatus.UNAVAILABLE
    http_status: int | None = None
    content_type: str | None = Field(default=None, max_length=100)
    response_bytes: int = Field(default=0, ge=0)
    redirect_count: int = Field(default=0, ge=0)
    cache_expires_at: datetime | None = None
    error_code: str | None = Field(default=None, max_length=100)
    safe_error_summary: str | None = Field(default=None, max_length=500)
    created_at: datetime = Field(default_factory=utc_now)


class EvidenceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    candidate_id: UUID
    source_page_id: UUID
    field_name: str = Field(min_length=1, max_length=100)
    extracted_value: str = Field(max_length=2000)
    normalized_value: str | None = Field(default=None, max_length=2000)
    evidence_locator: str | None = Field(default=None, max_length=500)
    short_evidence_text: str | None = Field(default=None, max_length=500)
    confidence: ConfidenceLevel
    extraction_version: str | None = Field(default=None, max_length=30)
    created_at: datetime = Field(default_factory=utc_now)


class ConflictRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    candidate_id: UUID
    field_name: str = Field(min_length=1, max_length=100)
    first_evidence_id: UUID
    second_evidence_id: UUID
    resolution_status: ResolutionStatus = ResolutionStatus.UNRESOLVED
    resolved_value: str | None = Field(default=None, max_length=2000)
    created_at: datetime = Field(default_factory=utc_now)
    resolved_at: datetime | None = None
    extraction_version: str | None = Field(default=None, max_length=30)
