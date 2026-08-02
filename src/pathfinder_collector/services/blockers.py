from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select

from pathfinder_collector.domain.evidence import SourcePage
from pathfinder_collector.enums import (
    CandidateStatus,
    ConfidenceLevel,
    FetchStatus,
    ResolutionStatus,
)
from pathfinder_collector.fetching.hashing import sha256_bytes
from pathfinder_collector.persistence.models import ContextConflictModel
from pathfinder_collector.persistence.repositories import (
    CandidateRepository,
    ExtractionEvidenceRepository,
)
from pathfinder_collector.services.extraction import CORE_FIELDS, agreement_confidence
from pathfinder_collector.services.review import APPROVAL_CORE_FIELDS, effective_candidate_data


class CandidateBlockers(BaseModel):
    candidate_id: UUID
    status: CandidateStatus
    missing_core_fields: list[str] = Field(default_factory=list)
    low_confidence_core_fields: list[str] = Field(default_factory=list)
    unresolved_conflicts: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    source_integrity: str = "ok"
    export_eligible: bool = False
    categories: list[str] = Field(default_factory=list)


class CandidateBlockerService:
    def __init__(
        self, candidates: CandidateRepository, evidence: ExtractionEvidenceRepository
    ) -> None:
        self.candidates = candidates
        self.evidence = evidence

    def analyze(self, candidate_id: UUID) -> CandidateBlockers:
        candidate = self.candidates.get(candidate_id)
        if candidate is None:
            raise ValueError("candidate does not exist")
        effective = effective_candidate_data(candidate, self.evidence.session)
        missing = sorted(
            field for field in APPROVAL_CORE_FIELDS if not str(effective.get(field, "")).strip()
        )
        records = self.evidence.evidence_for(candidate_id)
        low_fields: list[str] = []
        for field in sorted(CORE_FIELDS):
            field_records = [item for item in records if item.field_name == field]
            if field_records and agreement_confidence(field_records) is ConfidenceLevel.LOW:
                low_fields.append(field)
        conflicts = sorted(
            item.field_name
            for item in self.evidence.conflicts_for(candidate_id)
            if item.resolution_status is ResolutionStatus.UNRESOLVED
        )
        context_conflicts = list(
            self.evidence.session.scalars(
                select(ContextConflictModel.field_name).where(
                    ContextConflictModel.candidate_id == str(candidate_id),
                    ContextConflictModel.resolution_status == ResolutionStatus.UNRESOLVED.value,
                )
            ).all()
        )
        conflicts = sorted(set(conflicts + context_conflicts))
        integrity = self._source_integrity(candidate_id)
        categories: list[str] = []
        categories.extend(f"missing_{field}" for field in missing)
        if low_fields:
            categories.append("low_confidence_core_field")
        if conflicts:
            categories.append("unresolved_conflict")
        if candidate.extraction_warnings:
            categories.append("extraction_warning")
        if integrity != "ok":
            categories.append("cache_integrity")
        categories = list(dict.fromkeys(categories))
        blocking_categories = [item for item in categories if item != "extraction_warning"]
        eligible = (
            candidate.review_status
            in {
                CandidateStatus.APPROVED,
                CandidateStatus.EXPORTED,
            }
            and not blocking_categories
        )
        return CandidateBlockers(
            candidate_id=candidate.id,
            status=candidate.review_status,
            missing_core_fields=missing,
            low_confidence_core_fields=low_fields,
            unresolved_conflicts=conflicts,
            warnings=candidate.extraction_warnings,
            source_integrity=integrity,
            export_eligible=eligible,
            categories=categories,
        )

    def _source_integrity(self, candidate_id: UUID) -> str:
        sources = self.candidates.sources_for(candidate_id)
        if not sources:
            return "missing_source_relationship"
        for source, _role in sources:
            if not source.cached_file_path or not source.content_hash:
                return "missing_cache_metadata"
            try:
                content = Path(source.cached_file_path).read_bytes()
            except OSError:
                return "cache_missing"
            if sha256_bytes(content) != source.content_hash:
                return "cache_hash_mismatch"
        return "ok"


def inaccessible_source_category(source: SourcePage) -> str | None:
    if source.fetch_status not in {FetchStatus.FETCHED, FetchStatus.CACHE_HIT}:
        return "source_inaccessible"
    return None
