from typing import Protocol, TypeVar

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from pathfinder_collector.domain.candidates import CandidateRecord
from pathfinder_collector.domain.evidence import ConflictRecord, EvidenceRecord, SourcePage
from pathfinder_collector.domain.jobs import CollectionJob
from pathfinder_collector.enums import (
    EntityType,
    FetchStatus,
    JobStatus,
    RobotsStatus,
    SourceType,
)
from pathfinder_collector.persistence.models import (
    CandidateModel,
    CandidateSourceModel,
    ConflictModel,
    EvidenceModel,
    JobModel,
    SourcePageModel,
)


class JobRepositoryProtocol(Protocol):
    def add(self, job: CollectionJob) -> CollectionJob: ...

    def list(self) -> list[CollectionJob]: ...


RecordT = TypeVar("RecordT")


class RepositoryProtocol(Protocol[RecordT]):
    """Minimal persistence contract for foundation entities."""

    def add(self, record: RecordT) -> RecordT: ...

    def get(self, record_id: object) -> RecordT | None: ...


class CandidateRepositoryProtocol(RepositoryProtocol["CandidateRecord"], Protocol):
    pass


class SourcePageRepositoryProtocol(RepositoryProtocol["SourcePage"], Protocol):
    pass


class EvidenceRepositoryProtocol(RepositoryProtocol["EvidenceRecord"], Protocol):
    pass


class ConflictRepositoryProtocol(RepositoryProtocol["ConflictRecord"], Protocol):
    pass


class ExportRunRepositoryProtocol(RepositoryProtocol["ExportRun"], Protocol):
    pass


class JobRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, job: CollectionJob) -> CollectionJob:
        self.session.add(
            JobModel(
                id=str(job.id),
                name=job.name,
                country_code=job.country_code,
                entity_type=job.entity_type.value,
                requested_limit=job.requested_limit,
                status=job.status.value,
                created_at=job.created_at,
                updated_at=job.updated_at,
                error_code=job.error_code,
                safe_error_summary=job.safe_error_summary,
            )
        )
        self.session.commit()
        return job

    def list(self) -> list[CollectionJob]:
        rows = self.session.scalars(select(JobModel).order_by(JobModel.created_at)).all()
        return [
            CollectionJob(
                id=row.id,
                name=row.name,
                country_code=row.country_code,
                entity_type=EntityType(row.entity_type),
                requested_limit=row.requested_limit,
                status=JobStatus(row.status),
                created_at=row.created_at,
                updated_at=row.updated_at,
                error_code=row.error_code,
                safe_error_summary=row.safe_error_summary,
            )
            for row in rows
        ]

    def exists(self, job_id: object) -> bool:
        return self.session.get(JobModel, str(job_id)) is not None

    def get(self, job_id: object) -> CollectionJob | None:
        row = self.session.get(JobModel, str(job_id))
        if row is None:
            return None
        return CollectionJob(
            id=row.id,
            name=row.name,
            country_code=row.country_code,
            entity_type=EntityType(row.entity_type),
            requested_limit=row.requested_limit,
            status=JobStatus(row.status),
            created_at=row.created_at,
            updated_at=row.updated_at,
            error_code=row.error_code,
            safe_error_summary=row.safe_error_summary,
        )


class SourcePageRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def find(self, job_id: object, original_url: str) -> SourcePage | None:
        row = self.session.scalar(
            select(SourcePageModel).where(
                SourcePageModel.job_id == str(job_id),
                SourcePageModel.original_url == original_url,
            )
        )
        return self._domain(row) if row else None

    def list_for_job(self, job_id: object) -> list[SourcePage]:
        rows = self.session.scalars(
            select(SourcePageModel)
            .where(SourcePageModel.job_id == str(job_id))
            .order_by(SourcePageModel.created_at)
        ).all()
        return [self._domain(row) for row in rows]

    def save(self, page: SourcePage) -> SourcePage:
        row = self.session.get(SourcePageModel, str(page.id))
        if row is None:
            row = SourcePageModel(
                id=str(page.id), job_id=str(page.job_id), created_at=page.created_at
            )
            self.session.add(row)
        values = {
            "original_url": str(page.original_url),
            "normalized_url": str(page.normalized_url),
            "source_type": page.source_type.value,
            "official_domain": page.official_domain,
            "fetch_status": page.fetch_status.value,
            "content_hash": page.content_hash,
            "cached_file_path": page.cached_file_path,
            "fetched_at": page.fetched_at,
            "robots_status": page.robots_status.value,
            "http_status": page.http_status,
            "content_type": page.content_type,
            "response_bytes": page.response_bytes,
            "redirect_count": page.redirect_count,
            "cache_expires_at": page.cache_expires_at,
            "error_code": page.error_code,
            "safe_error_summary": page.safe_error_summary,
        }
        for name, value in values.items():
            setattr(row, name, value)
        self.session.commit()
        return page

    @staticmethod
    def _domain(row: SourcePageModel) -> SourcePage:
        return SourcePage(
            id=row.id,
            job_id=row.job_id,
            original_url=row.original_url,
            normalized_url=row.normalized_url,
            source_type=SourceType(row.source_type),
            official_domain=row.official_domain,
            fetch_status=FetchStatus(row.fetch_status),
            content_hash=row.content_hash,
            cached_file_path=row.cached_file_path,
            fetched_at=row.fetched_at,
            robots_status=RobotsStatus(row.robots_status),
            http_status=row.http_status,
            content_type=row.content_type,
            response_bytes=row.response_bytes,
            redirect_count=row.redirect_count,
            cache_expires_at=row.cache_expires_at,
            error_code=row.error_code,
            safe_error_summary=row.safe_error_summary,
            created_at=row.created_at,
        )


class CandidateRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def find_by_source(self, job_id: object, source_page_id: object) -> CandidateRecord | None:
        row = self.session.scalar(
            select(CandidateModel).where(
                CandidateModel.job_id == str(job_id),
                CandidateModel.source_page_id == str(source_page_id),
            )
        )
        return self._domain(row) if row else None

    def get(self, candidate_id: object) -> CandidateRecord | None:
        row = self.session.get(CandidateModel, str(candidate_id))
        return self._domain(row) if row else None

    def list_for_job(self, job_id: object) -> list[CandidateRecord]:
        rows = self.session.scalars(
            select(CandidateModel)
            .where(CandidateModel.job_id == str(job_id))
            .order_by(CandidateModel.created_at)
        ).all()
        return [self._domain(row) for row in rows]

    def attach_source(self, candidate_id: object, source_page_id: object, role: str) -> None:
        if role not in {"primary", "supporting"}:
            raise ValueError("source role must be primary or supporting")
        existing = self.session.scalar(
            select(CandidateSourceModel).where(
                CandidateSourceModel.candidate_id == str(candidate_id),
                CandidateSourceModel.source_page_id == str(source_page_id),
            )
        )
        if existing is None:
            self.session.add(
                CandidateSourceModel(
                    candidate_id=str(candidate_id),
                    source_page_id=str(source_page_id),
                    source_role=role,
                )
            )
        elif existing.source_role != "primary":
            existing.source_role = role
        self.session.commit()

    def sources_for(self, candidate_id: object) -> list[tuple[SourcePage, str]]:
        rows = self.session.execute(
            select(SourcePageModel, CandidateSourceModel.source_role)
            .join(CandidateSourceModel, CandidateSourceModel.source_page_id == SourcePageModel.id)
            .where(CandidateSourceModel.candidate_id == str(candidate_id))
            .order_by(CandidateSourceModel.created_at)
        ).all()
        return [(SourcePageRepository._domain(row), role) for row, role in rows]

    def save(self, candidate: CandidateRecord) -> CandidateRecord:
        row = self.session.get(CandidateModel, str(candidate.id))
        if row is None:
            row = CandidateModel(
                id=str(candidate.id), job_id=str(candidate.job_id), created_at=candidate.created_at
            )
            self.session.add(row)
        values = {
            "source_page_id": str(candidate.source_page_id) if candidate.source_page_id else None,
            "entity_type": candidate.entity_type.value,
            "review_status": candidate.review_status.value,
            "schema_version": candidate.schema_version,
            "normalized_data": candidate.normalized_data,
            "extraction_version": candidate.extraction_version,
            "last_extracted_at": candidate.last_extracted_at,
            "extraction_warnings": candidate.extraction_warnings,
            "reviewer_overrides": candidate.reviewer_overrides,
            "approved_at": candidate.approved_at,
            "updated_at": candidate.updated_at,
        }
        for name, value in values.items():
            setattr(row, name, value)
        self.session.commit()
        if candidate.source_page_id:
            self.attach_source(candidate.id, candidate.source_page_id, "primary")
        return candidate

    @staticmethod
    def _domain(row: CandidateModel) -> CandidateRecord:
        return CandidateRecord(
            id=row.id,
            job_id=row.job_id,
            source_page_id=row.source_page_id,
            entity_type=EntityType(row.entity_type),
            review_status=row.review_status,
            schema_version=row.schema_version,
            normalized_data=row.normalized_data,
            extraction_version=row.extraction_version,
            last_extracted_at=row.last_extracted_at,
            extraction_warnings=row.extraction_warnings or [],
            reviewer_overrides=row.reviewer_overrides or {},
            approved_at=row.approved_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


class ExtractionEvidenceRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def replace(
        self,
        candidate_id: object,
        version: str,
        evidence: list[EvidenceRecord],
        conflicts: list[ConflictRecord],
    ) -> None:
        evidence_ids = select(EvidenceModel.id).where(
            EvidenceModel.candidate_id == str(candidate_id),
            EvidenceModel.extraction_version == version,
        )
        self.session.execute(
            delete(ConflictModel).where(
                ConflictModel.candidate_id == str(candidate_id),
                ConflictModel.extraction_version == version,
            )
        )
        self.session.execute(delete(EvidenceModel).where(EvidenceModel.id.in_(evidence_ids)))
        for item in evidence:
            self.session.add(
                EvidenceModel(
                    id=str(item.id),
                    candidate_id=str(item.candidate_id),
                    source_page_id=str(item.source_page_id),
                    field_name=item.field_name,
                    extracted_value=item.extracted_value,
                    normalized_value=item.normalized_value,
                    evidence_locator=item.evidence_locator,
                    short_evidence_text=item.short_evidence_text,
                    confidence=item.confidence.value,
                    extraction_version=item.extraction_version,
                    created_at=item.created_at,
                )
            )
        self.session.flush()
        for item in conflicts:
            self.session.add(
                ConflictModel(
                    id=str(item.id),
                    candidate_id=str(item.candidate_id),
                    field_name=item.field_name,
                    first_evidence_id=str(item.first_evidence_id),
                    second_evidence_id=str(item.second_evidence_id),
                    resolution_status=item.resolution_status.value,
                    resolved_value=item.resolved_value,
                    created_at=item.created_at,
                    resolved_at=item.resolved_at,
                    extraction_version=item.extraction_version,
                )
            )
        self.session.commit()

    def replace_for_source(
        self,
        candidate_id: object,
        source_page_id: object,
        version: str,
        evidence: list[EvidenceRecord],
    ) -> None:
        evidence_ids = select(EvidenceModel.id).where(
            EvidenceModel.candidate_id == str(candidate_id),
            EvidenceModel.source_page_id == str(source_page_id),
            EvidenceModel.extraction_version == version,
        )
        self.session.execute(
            delete(ConflictModel).where(
                ConflictModel.candidate_id == str(candidate_id),
                ConflictModel.extraction_version == version,
            )
        )
        self.session.execute(delete(EvidenceModel).where(EvidenceModel.id.in_(evidence_ids)))
        for item in evidence:
            self.session.add(
                EvidenceModel(
                    id=str(item.id),
                    candidate_id=str(item.candidate_id),
                    source_page_id=str(item.source_page_id),
                    field_name=item.field_name,
                    extracted_value=item.extracted_value,
                    normalized_value=item.normalized_value,
                    evidence_locator=item.evidence_locator,
                    short_evidence_text=item.short_evidence_text,
                    confidence=item.confidence.value,
                    extraction_version=item.extraction_version,
                    created_at=item.created_at,
                )
            )
        self.session.commit()

    def replace_conflicts(
        self, candidate_id: object, version: str, conflicts: list[ConflictRecord]
    ) -> None:
        self.session.execute(
            delete(ConflictModel).where(
                ConflictModel.candidate_id == str(candidate_id),
                ConflictModel.extraction_version == version,
            )
        )
        for item in conflicts:
            self.session.add(
                ConflictModel(
                    id=str(item.id),
                    candidate_id=str(item.candidate_id),
                    field_name=item.field_name,
                    first_evidence_id=str(item.first_evidence_id),
                    second_evidence_id=str(item.second_evidence_id),
                    resolution_status=item.resolution_status.value,
                    resolved_value=item.resolved_value,
                    created_at=item.created_at,
                    resolved_at=item.resolved_at,
                    extraction_version=item.extraction_version,
                )
            )
        self.session.commit()

    def evidence_for(self, candidate_id: object) -> list[EvidenceRecord]:
        rows = self.session.scalars(
            select(EvidenceModel)
            .where(EvidenceModel.candidate_id == str(candidate_id))
            .order_by(EvidenceModel.field_name, EvidenceModel.created_at)
        ).all()
        return [
            EvidenceRecord(
                id=row.id,
                candidate_id=row.candidate_id,
                source_page_id=row.source_page_id,
                field_name=row.field_name,
                extracted_value=row.extracted_value,
                normalized_value=row.normalized_value,
                evidence_locator=row.evidence_locator,
                short_evidence_text=row.short_evidence_text,
                confidence=row.confidence,
                extraction_version=row.extraction_version,
                created_at=row.created_at,
            )
            for row in rows
        ]

    def conflicts_for(self, candidate_id: object) -> list[ConflictRecord]:
        rows = self.session.scalars(
            select(ConflictModel)
            .where(ConflictModel.candidate_id == str(candidate_id))
            .order_by(ConflictModel.field_name)
        ).all()
        return [
            ConflictRecord(
                id=row.id,
                candidate_id=row.candidate_id,
                field_name=row.field_name,
                first_evidence_id=row.first_evidence_id,
                second_evidence_id=row.second_evidence_id,
                resolution_status=row.resolution_status,
                resolved_value=row.resolved_value,
                created_at=row.created_at,
                resolved_at=row.resolved_at,
                extraction_version=row.extraction_version,
            )
            for row in rows
        ]
