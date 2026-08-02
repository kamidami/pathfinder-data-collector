from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from pathfinder_collector.domain.jobs import utc_now
from pathfinder_collector.enums import CandidateStatus, EntityType


class CandidateRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    job_id: UUID
    source_page_id: UUID | None = None
    entity_type: EntityType
    review_status: CandidateStatus = CandidateStatus.DISCOVERED
    schema_version: str = Field(min_length=1, max_length=30)
    normalized_data: dict[str, Any] = Field(default_factory=dict)
    extraction_version: str | None = Field(default=None, max_length=30)
    last_extracted_at: datetime | None = None
    extraction_warnings: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
