import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import SplitResult, urlsplit, urlunsplit
from uuid import UUID

from pydantic import AnyHttpUrl, TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from pathfinder_collector.domain.reviews import CandidateReview
from pathfinder_collector.enums import (
    CandidateStatus,
    EntityType,
    ResolutionStatus,
    ReviewDecision,
    StudyMode,
)
from pathfinder_collector.extraction.programmes import normalize_degree, normalize_language
from pathfinder_collector.fetching.hashing import sha256_bytes
from pathfinder_collector.persistence.models import (
    CandidateModel,
    CandidateReviewModel,
    ConflictModel,
    SourcePageModel,
)

OVERRIDE_FIELDS = {
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
APPROVAL_CORE_FIELDS = {
    "program_name",
    "university_name",
    "country_code",
    "degree_level",
    "teaching_language",
    "source_url",
}
_URL_ADAPTER = TypeAdapter(AnyHttpUrl)


class ReviewValidationError(ValueError):
    pass


class CandidateReviewService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def review_candidate(
        self,
        candidate_id: UUID,
        decision: ReviewDecision,
        reviewer_label: str,
        overrides: dict[str, Any] | None = None,
        notes: str | None = None,
        acknowledge_warnings: bool = False,
    ) -> CandidateReview:
        reviewer_label = _reviewer_label(reviewer_label)
        notes = _notes(notes)
        normalized_overrides = validate_overrides(overrides or {})
        candidate = self.session.get(CandidateModel, str(candidate_id))
        if candidate is None:
            raise ReviewValidationError("candidate does not exist")
        if candidate.entity_type != EntityType.PROGRAM.value:
            raise ReviewValidationError("only programme candidates can be reviewed")
        original_status = CandidateStatus(candidate.review_status)
        effective = dict(candidate.normalized_data or {})
        stored_overrides = dict(candidate.reviewer_overrides or {})
        stored_overrides.update(normalized_overrides)
        effective.update(stored_overrides)
        if decision is ReviewDecision.APPROVE:
            self._validate_approval(candidate, effective, acknowledge_warnings)
            resulting_status = CandidateStatus.APPROVED
        elif decision is ReviewDecision.REJECT:
            resulting_status = CandidateStatus.REJECTED
        else:
            resulting_status = CandidateStatus.NEEDS_REVIEW
        reviewed_at = datetime.now(UTC)
        last_reviewed_at = self.session.scalar(
            select(CandidateReviewModel.reviewed_at)
            .where(CandidateReviewModel.candidate_id == str(candidate_id))
            .order_by(CandidateReviewModel.reviewed_at.desc())
            .limit(1)
        )
        if last_reviewed_at is not None and reviewed_at <= last_reviewed_at:
            reviewed_at = last_reviewed_at + timedelta(microseconds=1)
        review = CandidateReview(
            candidate_id=candidate_id,
            reviewer_label=reviewer_label,
            decision=decision,
            review_notes=notes,
            field_overrides=normalized_overrides,
            acknowledged_warnings=acknowledge_warnings,
            original_status=original_status,
            resulting_status=resulting_status,
            reviewed_at=reviewed_at,
        )
        try:
            candidate.reviewer_overrides = stored_overrides
            candidate.review_status = resulting_status.value
            candidate.approved_at = (
                review.reviewed_at if resulting_status is CandidateStatus.APPROVED else None
            )
            candidate.updated_at = review.reviewed_at
            self.session.add(
                CandidateReviewModel(
                    id=str(review.id),
                    candidate_id=str(candidate_id),
                    reviewer_label=review.reviewer_label,
                    decision=review.decision.value,
                    review_notes=review.review_notes,
                    reviewed_at=review.reviewed_at,
                    field_overrides=review.field_overrides,
                    acknowledged_warnings=review.acknowledged_warnings,
                    original_status=review.original_status.value,
                    resulting_status=review.resulting_status.value,
                )
            )
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        return review

    def history(self, candidate_id: UUID) -> list[CandidateReview]:
        if self.session.get(CandidateModel, str(candidate_id)) is None:
            raise ReviewValidationError("candidate does not exist")
        rows = self.session.scalars(
            select(CandidateReviewModel)
            .where(CandidateReviewModel.candidate_id == str(candidate_id))
            .order_by(CandidateReviewModel.reviewed_at, CandidateReviewModel.id)
        ).all()
        return [
            CandidateReview(
                id=row.id,
                candidate_id=row.candidate_id,
                reviewer_label=row.reviewer_label,
                decision=row.decision,
                review_notes=row.review_notes,
                reviewed_at=row.reviewed_at,
                field_overrides=row.field_overrides or {},
                acknowledged_warnings=row.acknowledged_warnings,
                original_status=row.original_status,
                resulting_status=row.resulting_status,
            )
            for row in rows
        ]

    def _validate_approval(
        self, candidate: CandidateModel, effective: dict[str, Any], acknowledge_warnings: bool
    ) -> None:
        if candidate.source_page_id is None:
            raise ReviewValidationError("approval requires a source relationship")
        source = self.session.get(SourcePageModel, candidate.source_page_id)
        if source is None or not source.cached_file_path or not source.content_hash:
            raise ReviewValidationError("approval requires an intact cached source")
        try:
            content = Path(source.cached_file_path).read_bytes()
        except OSError as exc:
            raise ReviewValidationError("approval requires an intact cached source") from exc
        if sha256_bytes(content) != source.content_hash:
            raise ReviewValidationError("source cache hash does not match")
        unresolved = self.session.scalar(
            select(ConflictModel.id).where(
                ConflictModel.candidate_id == candidate.id,
                ConflictModel.resolution_status == ResolutionStatus.UNRESOLVED.value,
            )
        )
        if unresolved:
            raise ReviewValidationError("unresolved conflicts block approval")
        missing = sorted(
            field for field in APPROVAL_CORE_FIELDS if not str(effective.get(field, "")).strip()
        )
        if missing:
            raise ReviewValidationError(f"missing required approval fields: {', '.join(missing)}")
        validate_effective_programme(effective)
        if candidate.extraction_warnings and not acknowledge_warnings:
            raise ReviewValidationError("non-blocking extraction warnings must be acknowledged")


def validate_overrides(overrides: dict[str, Any]) -> dict[str, str]:
    unknown = set(overrides) - OVERRIDE_FIELDS
    if unknown:
        raise ReviewValidationError(f"unknown override fields: {', '.join(sorted(unknown))}")
    result: dict[str, str] = {}
    for field, raw in overrides.items():
        if not isinstance(raw, (str, int)) or isinstance(raw, bool):
            raise ReviewValidationError(f"override {field} must be a string or integer")
        value = str(raw).strip()
        if len(value) > 2000:
            raise ReviewValidationError(f"override {field} is too long")
        if not value:
            result[field] = ""
            continue
        if field == "country_code":
            value = value.upper()
            if not re.fullmatch(r"[A-Z]{2}", value):
                raise ReviewValidationError("country_code must be two ASCII letters")
        elif field == "degree_level":
            value = normalize_degree(value) or value.lower()
            if value not in {"bachelor", "master", "phd"}:
                raise ReviewValidationError("degree_level is unsupported")
        elif field == "teaching_language":
            value = normalize_language(value) or ""
            if not value:
                raise ReviewValidationError("teaching_language is unsupported")
        elif field == "study_mode":
            try:
                value = StudyMode(value).value
            except ValueError as exc:
                raise ReviewValidationError("study_mode is unsupported") from exc
        elif field == "duration_unit" and value not in {"semesters", "years", "months"}:
            raise ReviewValidationError("duration_unit is unsupported")
        elif field in {"duration_value", "duration_semesters"}:
            if not value.isdigit() or int(value) <= 0:
                raise ReviewValidationError(f"{field} must be a positive integer")
        elif field in {"application_url", "source_url"}:
            value = _safe_url(value)
            if field == "source_url":
                parts = urlsplit(value)
                value = urlunsplit(SplitResult(parts.scheme, parts.netloc, parts.path, "", ""))
        result[field] = value
    return result


def validate_effective_programme(data: dict[str, Any]) -> None:
    validate_overrides({field: value for field, value in data.items() if field in OVERRIDE_FIELDS})
    _safe_url(str(data["source_url"]))


def effective_candidate_data(candidate: CandidateModel) -> dict[str, str]:
    result = {key: str(value) for key, value in (candidate.normalized_data or {}).items()}
    result.update({key: str(value) for key, value in (candidate.reviewer_overrides or {}).items()})
    return result


def _safe_url(value: str) -> str:
    try:
        parsed = _URL_ADAPTER.validate_python(value)
    except ValidationError as exc:
        raise ReviewValidationError("URL override must be an HTTP(S) URL") from exc
    parts = urlsplit(str(parsed))
    if parts.scheme not in {"http", "https"} or parts.username or parts.password:
        raise ReviewValidationError("URL override must be a credential-free HTTP(S) URL")
    return str(parsed)


def _reviewer_label(value: str) -> str:
    value = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_. -]{0,49}", value) or "@" in value:
        raise ReviewValidationError("reviewer label must be a short local operator label")
    return value


def _notes(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if len(value) > 1000:
        raise ReviewValidationError("review notes exceed 1000 characters")
    return value or None
