from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from pathfinder_collector.enums import EntityType, JobStatus


def utc_now() -> datetime:
    return datetime.now(UTC)


class CollectionJob(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=200)
    country_code: str
    entity_type: EntityType
    requested_limit: int = Field(gt=0)
    status: JobStatus = JobStatus.PENDING
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    error_code: str | None = Field(default=None, max_length=100)
    safe_error_summary: str | None = Field(default=None, max_length=500)

    @field_validator("country_code")
    @classmethod
    def country_code_is_iso_style(cls, value: str) -> str:
        normalized = value.upper()
        if len(normalized) != 2 or not normalized.isalpha() or not normalized.isascii():
            raise ValueError("country code must contain exactly two ASCII letters")
        return normalized
