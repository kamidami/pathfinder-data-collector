import re
from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from pathfinder_collector.enums import (
    CandidateStatus,
    ConflictResolutionAction,
    ResolutionStatus,
)
from pathfinder_collector.persistence.models import (
    CandidateModel,
    ConflictModel,
    ConflictResolutionModel,
    EvidenceModel,
)
from pathfinder_collector.services.review import APPROVAL_CORE_FIELDS, validate_overrides


class ConflictView(BaseModel):
    id: UUID
    candidate_id: UUID
    field_name: str
    first_value: str
    second_value: str
    status: ResolutionStatus
    resolved_value: str | None = None


class ConflictResolutionService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_for_candidate(self, candidate_id: UUID) -> list[ConflictView]:
        rows = self.session.scalars(
            select(ConflictModel)
            .where(ConflictModel.candidate_id == str(candidate_id))
            .order_by(ConflictModel.field_name, ConflictModel.created_at)
        ).all()
        return [self._view(row) for row in rows]

    def resolve(
        self,
        conflict_id: UUID,
        action: ConflictResolutionAction,
        reviewer: str,
        notes: str,
        overrides: dict[str, object] | None = None,
    ) -> ConflictView:
        reviewer = reviewer.strip()
        notes = notes.strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_. -]{0,49}", reviewer) or "@" in reviewer:
            raise ValueError("reviewer label is invalid")
        if not notes or len(notes) > 1000:
            raise ValueError("a bounded conflict-resolution note is required")
        conflict = self.session.get(ConflictModel, str(conflict_id))
        if conflict is None:
            raise ValueError("conflict does not exist")
        candidate = self.session.get(CandidateModel, conflict.candidate_id)
        first = self.session.get(EvidenceModel, conflict.first_evidence_id)
        second = self.session.get(EvidenceModel, conflict.second_evidence_id)
        if candidate is None or first is None or second is None:
            raise ValueError("conflict evidence is unavailable")
        selected: str | None = None
        if action is ConflictResolutionAction.SELECT_FIRST:
            selected = first.normalized_value or first.extracted_value
        elif action is ConflictResolutionAction.SELECT_SECOND:
            selected = second.normalized_value or second.extracted_value
        elif action is ConflictResolutionAction.CLEAR_OPTIONAL_FIELD:
            if conflict.field_name in APPROVAL_CORE_FIELDS:
                raise ValueError("core fields cannot be cleared")
            selected = ""
        elif action is ConflictResolutionAction.REVIEWER_OVERRIDE:
            validated = validate_overrides(overrides or {})
            if set(validated) != {conflict.field_name}:
                raise ValueError("override must contain exactly the conflicted field")
            selected = validated[conflict.field_name]
            official_values = {
                first.normalized_value or first.extracted_value,
                second.normalized_value or second.extracted_value,
            }
            if selected not in official_values:
                raise ValueError("conflict override must match retained official evidence")
        elif action is not ConflictResolutionAction.KEEP_UNRESOLVED:
            raise ValueError("unsupported conflict resolution")

        if action is ConflictResolutionAction.KEEP_UNRESOLVED:
            conflict.resolution_status = ResolutionStatus.UNRESOLVED.value
            conflict.resolved_value = None
            conflict.resolved_at = None
        else:
            conflict.resolution_status = ResolutionStatus.RESOLVED.value
            conflict.resolved_value = selected
            conflict.resolved_at = datetime.now(UTC)
            overrides_data = dict(candidate.reviewer_overrides or {})
            overrides_data[conflict.field_name] = selected or ""
            candidate.reviewer_overrides = overrides_data
        candidate.review_status = CandidateStatus.NEEDS_REVIEW.value
        candidate.updated_at = datetime.now(UTC)
        self.session.add(
            ConflictResolutionModel(
                id=str(uuid4()),
                conflict_id=conflict.id,
                candidate_id=candidate.id,
                field_name=conflict.field_name,
                resolution_action=action.value,
                selected_value=selected,
                reviewer_label=reviewer,
                review_notes=notes,
                reviewed_at=datetime.now(UTC),
            )
        )
        self.session.commit()
        return self._view(conflict)

    def history(self, candidate_id: UUID) -> list[ConflictResolutionModel]:
        return list(
            self.session.scalars(
                select(ConflictResolutionModel)
                .where(ConflictResolutionModel.candidate_id == str(candidate_id))
                .order_by(ConflictResolutionModel.reviewed_at)
            ).all()
        )

    def _view(self, conflict: ConflictModel) -> ConflictView:
        first = self.session.get(EvidenceModel, conflict.first_evidence_id)
        second = self.session.get(EvidenceModel, conflict.second_evidence_id)
        if first is None or second is None:
            raise ValueError("conflict evidence is unavailable")
        return ConflictView(
            id=UUID(conflict.id),
            candidate_id=UUID(conflict.candidate_id),
            field_name=conflict.field_name,
            first_value=first.normalized_value or first.extracted_value,
            second_value=second.normalized_value or second.extracted_value,
            status=ResolutionStatus(conflict.resolution_status),
            resolved_value=conflict.resolved_value,
        )
