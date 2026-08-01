from uuid import uuid4

import pytest
from pydantic import ValidationError

from pathfinder_collector.domain.evidence import EvidenceRecord
from pathfinder_collector.domain.jobs import CollectionJob
from pathfinder_collector.enums import ConfidenceLevel, EntityType, JobStatus


def test_enum_validation() -> None:
    job = CollectionJob(name="job", country_code="de", entity_type="program", requested_limit=1)
    assert job.status is JobStatus.PENDING
    assert job.entity_type is EntityType.PROGRAM


@pytest.mark.parametrize("country", ["D", "DEU", "D1", "éx", ""])
def test_invalid_country_code_rejected(country: str) -> None:
    with pytest.raises(ValidationError):
        CollectionJob(name="job", country_code=country, entity_type="program", requested_limit=1)


@pytest.mark.parametrize("limit", [0, -1])
def test_non_positive_limit_rejected(limit: int) -> None:
    with pytest.raises(ValidationError):
        CollectionJob(name="job", country_code="DE", entity_type="program", requested_limit=limit)


def test_evidence_text_has_conservative_limit() -> None:
    with pytest.raises(ValidationError):
        EvidenceRecord(
            candidate_id=uuid4(),
            source_page_id=uuid4(),
            field_name="tuition",
            extracted_value="value",
            short_evidence_text="x" * 501,
            confidence=ConfidenceLevel.HIGH,
        )
