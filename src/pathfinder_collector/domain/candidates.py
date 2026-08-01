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
    entity_type: EntityType
    review_status: CandidateStatus = CandidateStatus.DISCOVERED
    schema_version: str = Field(min_length=1, max_length=30)
    normalized_data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
