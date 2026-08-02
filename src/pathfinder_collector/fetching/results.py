from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from pathfinder_collector.enums import FetchStatus, RobotsStatus


class FetchResult(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    source_page_id: UUID = Field(default_factory=uuid4)
    requested_url: str
    final_normalized_url: str | None = None
    safe_display_url: str | None = None
    status: FetchStatus
    http_status: int | None = None
    content_type: str | None = None
    response_bytes: int = 0
    content_hash: str | None = None
    cache_path: Path | None = None
    fetched_at: datetime | None = None
    cache_hit: bool = False
    robots_status: RobotsStatus
    redirect_count: int = 0
    safe_error_code: str | None = Field(default=None, max_length=100)
    safe_error_summary: str | None = Field(default=None, max_length=500)
