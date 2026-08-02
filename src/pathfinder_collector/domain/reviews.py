from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from pathfinder_collector.domain.jobs import utc_now
from pathfinder_collector.enums import CandidateStatus, ReviewDecision


class CandidateReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    candidate_id: UUID
    reviewer_label: str = Field(min_length=1, max_length=50)
    decision: ReviewDecision
    review_notes: str | None = Field(default=None, max_length=1000)
    reviewed_at: datetime = Field(default_factory=utc_now)
    field_overrides: dict[str, str] = Field(default_factory=dict)
    acknowledged_warnings: bool = False
    original_status: CandidateStatus
    resulting_status: CandidateStatus
