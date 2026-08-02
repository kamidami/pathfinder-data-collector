from typing import Protocol, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from pathfinder_collector.domain.evidence import SourcePage
from pathfinder_collector.domain.jobs import CollectionJob
from pathfinder_collector.enums import (
    EntityType,
    FetchStatus,
    JobStatus,
    RobotsStatus,
    SourceType,
)
from pathfinder_collector.persistence.models import JobModel, SourcePageModel


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
