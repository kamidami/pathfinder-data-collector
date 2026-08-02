from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from pathfinder_collector.enums import CandidateStatus, ConfidenceLevel, ExtractionStatus


class FieldSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_name: str
    extracted_value: str = Field(max_length=2000)
    normalized_value: str | None = Field(default=None, max_length=2000)
    evidence_locator: str = Field(max_length=500)
    short_evidence_text: str = Field(max_length=500)
    confidence: ConfidenceLevel
    priority: int = Field(ge=1, le=3)


class ExtractorOutput(BaseModel):
    suggestions: list[FieldSuggestion] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    programme_context: bool = False


class ProgrammeExtractionResult(BaseModel):
    source_page_id: UUID
    candidate_id: UUID | None = None
    fields_found: list[str] = Field(default_factory=list)
    fields_missing: list[str] = Field(default_factory=list)
    evidence_count: int = 0
    conflicts_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    extraction_status: ExtractionStatus
    candidate_status: CandidateStatus | None = None
    created_candidate: bool = False
    updated_candidate: bool = False
