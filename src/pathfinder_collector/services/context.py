import re
from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from pathfinder_collector.persistence.models import (
    CandidateContextModel,
    CandidateModel,
    ContextConflictModel,
    EvidenceModel,
    JobModel,
)

CONTEXT_FIELD_ALLOWLIST = frozenset({"country_code"})
OPERATOR_JOB_CONTEXT = "operator_job_context"


class CandidateContextSummary(BaseModel):
    candidate_id: UUID
    job_country: str
    effective_country: str | None = None
    provenance: str | None = None
    source_contradictions: list[str] = Field(default_factory=list)
    approval_eligible: bool = False


class CandidateContextService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def apply_job_country(self, candidate_id: UUID) -> CandidateContextSummary:
        candidate, job = self._candidate_job(candidate_id)
        country = job.country_code.strip().upper()
        if not re.fullmatch(r"[A-Z]{2}", country):
            raise ValueError("job country must be two ASCII letters")
        existing = self.session.scalar(
            select(CandidateContextModel).where(
                CandidateContextModel.candidate_id == candidate.id,
                CandidateContextModel.field_name == "country_code",
                CandidateContextModel.source_job_id == job.id,
            )
        )
        if existing is None:
            self.session.add(
                CandidateContextModel(
                    id=str(uuid4()),
                    candidate_id=candidate.id,
                    field_name="country_code",
                    value=country,
                    source_type=OPERATOR_JOB_CONTEXT,
                    source_job_id=job.id,
                    effective=True,
                    created_at=datetime.now(UTC),
                )
            )
            self.session.flush()
        elif existing.value != country or existing.source_type != OPERATOR_JOB_CONTEXT:
            raise ValueError("stored job context does not match the collection job")
        self.refresh_candidate(candidate_id)
        self.session.commit()
        return self.summary(candidate_id)

    def refresh_candidate(self, candidate_id: UUID) -> None:
        contexts = self.session.scalars(
            select(CandidateContextModel).where(
                CandidateContextModel.candidate_id == str(candidate_id)
            )
        ).all()
        self.session.execute(
            delete(ContextConflictModel).where(
                ContextConflictModel.candidate_id == str(candidate_id)
            )
        )
        for context in contexts:
            if context.field_name not in CONTEXT_FIELD_ALLOWLIST:
                context.effective = False
                continue
            contradictions = self.session.scalars(
                select(EvidenceModel).where(
                    EvidenceModel.candidate_id == str(candidate_id),
                    EvidenceModel.field_name == context.field_name,
                    EvidenceModel.normalized_value.is_not(None),
                    EvidenceModel.normalized_value != context.value,
                )
            ).all()
            context.effective = not contradictions
            for evidence in contradictions:
                self.session.add(
                    ContextConflictModel(
                        id=str(uuid4()),
                        candidate_id=str(candidate_id),
                        field_name=context.field_name,
                        context_value_id=context.id,
                        evidence_id=evidence.id,
                        resolution_status="unresolved",
                        created_at=datetime.now(UTC),
                    )
                )
        self.session.flush()

    def summary(self, candidate_id: UUID) -> CandidateContextSummary:
        candidate, job = self._candidate_job(candidate_id)
        context = self.session.scalar(
            select(CandidateContextModel).where(
                CandidateContextModel.candidate_id == candidate.id,
                CandidateContextModel.field_name == "country_code",
                CandidateContextModel.source_job_id == job.id,
            )
        )
        contradictions: list[str] = []
        if context:
            contradictions = list(
                self.session.scalars(
                    select(EvidenceModel.normalized_value)
                    .join(
                        ContextConflictModel,
                        ContextConflictModel.evidence_id == EvidenceModel.id,
                    )
                    .where(ContextConflictModel.context_value_id == context.id)
                    .distinct()
                    .order_by(EvidenceModel.normalized_value)
                ).all()
            )
        return CandidateContextSummary(
            candidate_id=UUID(candidate.id),
            job_country=job.country_code,
            effective_country=context.value if context and context.effective else None,
            provenance=context.source_type if context else None,
            source_contradictions=contradictions,
            approval_eligible=bool(context and context.effective and not contradictions),
        )

    def _candidate_job(self, candidate_id: UUID) -> tuple[CandidateModel, JobModel]:
        candidate = self.session.get(CandidateModel, str(candidate_id))
        if candidate is None:
            raise ValueError("candidate does not exist")
        job = self.session.get(JobModel, candidate.job_id)
        if job is None:
            raise ValueError("candidate collection job does not exist")
        return candidate, job


def effective_context_values(session: Session, candidate_id: object) -> dict[str, str]:
    rows = session.scalars(
        select(CandidateContextModel).where(
            CandidateContextModel.candidate_id == str(candidate_id),
            CandidateContextModel.effective.is_(True),
        )
    ).all()
    return {row.field_name: row.value for row in rows if row.field_name in CONTEXT_FIELD_ALLOWLIST}
