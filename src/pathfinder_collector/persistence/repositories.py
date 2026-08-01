from typing import Protocol, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from pathfinder_collector.domain.jobs import CollectionJob
from pathfinder_collector.enums import EntityType, JobStatus
from pathfinder_collector.persistence.models import JobModel


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
