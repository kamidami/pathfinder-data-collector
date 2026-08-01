from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from pathfinder_collector.domain.jobs import utc_now
from pathfinder_collector.enums import EntityType, ExportStatus


class ExportRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    entity_type: EntityType
    schema_version: str = Field(min_length=1, max_length=30)
    record_count: int = Field(ge=0)
    export_path: str = Field(min_length=1, max_length=500)
    status: ExportStatus = ExportStatus.PENDING
    created_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None
