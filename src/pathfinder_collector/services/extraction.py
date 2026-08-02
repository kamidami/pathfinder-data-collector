from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from pathfinder_collector.domain.candidates import CandidateRecord
from pathfinder_collector.domain.evidence import ConflictRecord, EvidenceRecord
from pathfinder_collector.enums import (
    CandidateStatus,
    ConfidenceLevel,
    EntityType,
    ExtractionStatus,
    FetchStatus,
)
from pathfinder_collector.extraction.programmes import ProgrammeExtractor
from pathfinder_collector.extraction.results import (
    FieldSuggestion,
    ProgrammeExtractionResult,
)
from pathfinder_collector.fetching.hashing import sha256_bytes
from pathfinder_collector.persistence.repositories import (
    CandidateRepository,
    ExtractionEvidenceRepository,
    JobRepository,
    SourcePageRepository,
)

EXTRACTION_VERSION = "programme-v1"
SUPPORTED_FIELDS = {
    "program_name",
    "university_name",
    "country_code",
    "city",
    "degree_level",
    "field_category",
    "teaching_language",
    "duration_value",
    "duration_unit",
    "duration_semesters",
    "study_mode",
    "intake",
    "application_url",
    "source_url",
}
CORE_FIELDS = {
    "program_name",
    "university_name",
    "degree_level",
    "teaching_language",
    "source_url",
}


class ProgrammeExtractionService:
    def __init__(
        self,
        jobs: JobRepository,
        sources: SourcePageRepository,
        candidates: CandidateRepository,
        evidence: ExtractionEvidenceRepository,
        extractor: ProgrammeExtractor | None = None,
    ) -> None:
        self.jobs = jobs
        self.sources = sources
        self.candidates = candidates
        self.evidence = evidence
        self.extractor = extractor or ProgrammeExtractor()

    def extract_source(
        self, job_id: UUID, source_page_id: UUID, *, force: bool = False
    ) -> ProgrammeExtractionResult:
        del force  # deterministic replacement is idempotent; retained for CLI/API compatibility.
        job = self.jobs.get(job_id)
        if job is None:
            raise ValueError("collection job does not exist")
        if job.entity_type is not EntityType.PROGRAM:
            raise ValueError("collection job entity type must be program")
        source = next(
            (item for item in self.sources.list_for_job(job_id) if item.id == source_page_id), None
        )
        if source is None:
            raise ValueError("source page does not exist or does not belong to the job")
        if source.fetch_status not in {FetchStatus.FETCHED, FetchStatus.CACHE_HIT}:
            return self._failure(source_page_id, ExtractionStatus.UNSUPPORTED_SOURCE)
        if source.content_type not in {"text/html", "application/xhtml+xml"}:
            return self._failure(source_page_id, ExtractionStatus.UNSUPPORTED_SOURCE)
        if not source.cached_file_path:
            return self._failure(source_page_id, ExtractionStatus.CACHE_MISSING)
        path = Path(source.cached_file_path)
        try:
            content = path.read_bytes()
        except OSError:
            return self._failure(source_page_id, ExtractionStatus.CACHE_MISSING)
        if not source.content_hash or sha256_bytes(content) != source.content_hash:
            return self._failure(source_page_id, ExtractionStatus.CACHE_CORRUPT)
        try:
            output = self.extractor.extract(content, str(source.normalized_url))
        except Exception as exc:
            return ProgrammeExtractionResult(
                source_page_id=source_page_id,
                extraction_status=ExtractionStatus.EXTRACTION_FAILED,
                warnings=[f"Extraction failed safely: {type(exc).__name__}"],
            )
        if not output.programme_context:
            return ProgrammeExtractionResult(
                source_page_id=source_page_id,
                extraction_status=ExtractionStatus.NO_PROGRAMME_DATA,
                warnings=output.warnings,
            )

        existing = self.candidates.find_by_source(job_id, source_page_id)
        candidate = existing or CandidateRecord(
            job_id=job_id,
            source_page_id=source_page_id,
            entity_type=EntityType.PROGRAM,
            schema_version="pathfinder-v1",
        )
        normalized, conflicts_by_field, warnings = _resolve(output.suggestions)
        warnings = output.warnings + warnings
        missing = sorted(SUPPORTED_FIELDS - set(normalized))
        low_confidence = {
            item.field_name for item in output.suggestions if item.confidence is ConfidenceLevel.LOW
        }
        review_status = (
            CandidateStatus.COLLECTED
            if not (CORE_FIELDS - set(normalized)) and not conflicts_by_field and not low_confidence
            else CandidateStatus.NEEDS_REVIEW
        )
        if candidate.review_status not in {
            CandidateStatus.APPROVED,
            CandidateStatus.REJECTED,
            CandidateStatus.EXPORTED,
        }:
            candidate.review_status = review_status
        now = datetime.now(UTC)
        candidate.normalized_data = _contract_aware_data(normalized)
        candidate.extraction_version = EXTRACTION_VERSION
        candidate.last_extracted_at = now
        candidate.extraction_warnings = warnings
        candidate.updated_at = now
        self.candidates.save(candidate)

        records = [_evidence(candidate.id, source_page_id, item) for item in output.suggestions]
        by_field: dict[str, list[EvidenceRecord]] = defaultdict(list)
        for record in records:
            by_field[record.field_name].append(record)
        conflicts = [
            ConflictRecord(
                candidate_id=candidate.id,
                field_name=field,
                first_evidence_id=by_field[field][indexes[0]].id,
                second_evidence_id=by_field[field][indexes[1]].id,
                extraction_version=EXTRACTION_VERSION,
            )
            for field, indexes in conflicts_by_field.items()
        ]
        self.evidence.replace(candidate.id, EXTRACTION_VERSION, records, conflicts)
        status = (
            ExtractionStatus.EXTRACTED
            if review_status is CandidateStatus.COLLECTED
            else ExtractionStatus.PARTIAL
        )
        return ProgrammeExtractionResult(
            source_page_id=source_page_id,
            candidate_id=candidate.id,
            fields_found=sorted(normalized),
            fields_missing=missing,
            evidence_count=len(records),
            conflicts_count=len(conflicts),
            warnings=warnings,
            extraction_status=status,
            candidate_status=candidate.review_status,
            created_candidate=existing is None,
            updated_candidate=existing is not None,
        )

    @staticmethod
    def _failure(source_page_id: UUID, status: ExtractionStatus) -> ProgrammeExtractionResult:
        return ProgrammeExtractionResult(source_page_id=source_page_id, extraction_status=status)


def _resolve(
    suggestions: list[FieldSuggestion],
) -> tuple[dict[str, str], dict[str, tuple[int, int]], list[str]]:
    grouped: dict[str, list[FieldSuggestion]] = defaultdict(list)
    for item in suggestions:
        if item.field_name in SUPPORTED_FIELDS:
            grouped[item.field_name].append(item)
    normalized: dict[str, str] = {}
    conflicts: dict[str, tuple[int, int]] = {}
    warnings: list[str] = []
    for field, items in grouped.items():
        values: dict[str, list[int]] = defaultdict(list)
        for index, item in enumerate(items):
            value = item.normalized_value or item.extracted_value
            values[value.casefold()].append(index)
        if len(values) == 1:
            best = min(items, key=lambda item: item.priority)
            if best.confidence is not ConfidenceLevel.LOW:
                normalized[field] = best.normalized_value or best.extracted_value
            continue
        best_priority = min(item.priority for item in items)
        best_indexes = [index for index, item in enumerate(items) if item.priority == best_priority]
        best_values = {
            (items[index].normalized_value or items[index].extracted_value).casefold()
            for index in best_indexes
        }
        if len(best_values) == 1 and any(item.priority > best_priority for item in items):
            best = items[best_indexes[0]]
            normalized[field] = best.normalized_value or best.extracted_value
            warnings.append(f"Lower-priority conflicting {field} evidence requires review")
        else:
            first_value = next(iter(values.values()))[0]
            second_value = next(
                indexes[0] for key, indexes in values.items() if indexes[0] != first_value
            )
            conflicts[field] = (first_value, second_value)
    return normalized, conflicts, warnings


def _evidence(candidate_id: UUID, source_page_id: UUID, item: FieldSuggestion) -> EvidenceRecord:
    return EvidenceRecord(
        candidate_id=candidate_id,
        source_page_id=source_page_id,
        field_name=item.field_name,
        extracted_value=item.extracted_value,
        normalized_value=item.normalized_value,
        evidence_locator=item.evidence_locator,
        short_evidence_text=item.short_evidence_text,
        confidence=item.confidence,
        extraction_version=EXTRACTION_VERSION,
    )


def _contract_aware_data(values: dict[str, str]) -> dict[str, str]:
    data = dict(values)
    if "teaching_language" in values:
        data["language"] = values["teaching_language"]
    if "duration_value" in values and "duration_unit" in values:
        data["duration"] = f"{values['duration_value']} {values['duration_unit']}"
    return data
