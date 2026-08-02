import csv
import json
from pathlib import Path

import pytest
from sqlalchemy import func, select

from pathfinder_collector.config import Settings
from pathfinder_collector.database import (
    create_collector_engine,
    initialize_database,
    session_scope,
)
from pathfinder_collector.domain.evidence import SourcePage
from pathfinder_collector.domain.jobs import CollectionJob
from pathfinder_collector.enums import (
    CandidateStatus,
    EntityType,
    FetchStatus,
    ReviewDecision,
    RobotsStatus,
    SourceType,
)
from pathfinder_collector.fetching.hashing import sha256_bytes
from pathfinder_collector.persistence.models import CandidateModel, CandidateReviewModel
from pathfinder_collector.persistence.repositories import (
    CandidateRepository,
    ExtractionEvidenceRepository,
    JobRepository,
    SourcePageRepository,
)
from pathfinder_collector.services.exporting import PathfinderExportService
from pathfinder_collector.services.extraction import ProgrammeExtractionService
from pathfinder_collector.services.review import CandidateReviewService, ReviewValidationError

FIXTURES = Path(__file__).parent / "fixtures"


def extracted_candidate(
    session: object,
    settings: Settings,
    *,
    url: str = "https://example.test/programme",
    fixture: str = "programme_labelled.html",
):
    job = JobRepository(session).add(
        CollectionJob(
            name="review", country_code="DE", entity_type=EntityType.PROGRAM, requested_limit=2
        )
    )
    content = (FIXTURES / fixture).read_bytes()
    cache_path = settings.cache_dir / f"{job.id}.html"
    cache_path.write_bytes(content)
    source = SourcePageRepository(session).save(
        SourcePage(
            job_id=job.id,
            original_url=url,
            normalized_url=url,
            source_type=SourceType.OFFICIAL_PROGRAM,
            official_domain=True,
            fetch_status=FetchStatus.FETCHED,
            robots_status=RobotsStatus.ALLOWED,
            content_type="text/html",
            response_bytes=len(content),
            content_hash=sha256_bytes(content),
            cached_file_path=str(cache_path),
        )
    )
    result = ProgrammeExtractionService(
        JobRepository(session),
        SourcePageRepository(session),
        CandidateRepository(session),
        ExtractionEvidenceRepository(session),
    ).extract_source(job.id, source.id)
    return job, source, result


def test_approval_is_explicit_and_preserves_overrides_and_evidence(temp_settings: Settings) -> None:
    engine = create_collector_engine(temp_settings.database_url)
    initialize_database(engine)
    with session_scope(engine) as session:
        _, _, extraction = extracted_candidate(session, temp_settings)
        candidate = CandidateRepository(session).get(extraction.candidate_id)
        assert candidate.review_status is CandidateStatus.COLLECTED
        evidence_before = session.scalar(
            select(func.count()).select_from(
                __import__(
                    "pathfinder_collector.persistence.models", fromlist=["EvidenceModel"]
                ).EvidenceModel
            )
        )
        review = CandidateReviewService(session).review_candidate(
            extraction.candidate_id,
            ReviewDecision.APPROVE,
            "operator-1",
            {"city": "Munich"},
        )
        assert review.resulting_status is CandidateStatus.APPROVED
        candidate = CandidateRepository(session).get(extraction.candidate_id)
        assert candidate.reviewer_overrides == {"city": "Munich"}
        assert candidate.normalized_data["city"] == "Berlin"
        assert (
            session.scalar(
                select(func.count()).select_from(
                    __import__(
                        "pathfinder_collector.persistence.models", fromlist=["EvidenceModel"]
                    ).EvidenceModel
                )
            )
            == evidence_before
        )
    engine.dispose()


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"internal_id": "x"}, "unknown override"),
        ({"country_code": "D1"}, "country_code"),
        ({"degree_level": "wizard"}, "degree_level"),
        ({"study_mode": "weekends"}, "study_mode"),
        ({"source_url": "file:///tmp/x"}, "HTTP"),
        ({"program_name": ""}, "missing required"),
    ],
)
def test_invalid_or_required_clearing_override_blocks_approval(
    temp_settings: Settings, overrides: dict[str, str], message: str
) -> None:
    engine = create_collector_engine(temp_settings.database_url)
    initialize_database(engine)
    with session_scope(engine) as session:
        _, _, extraction = extracted_candidate(session, temp_settings)
        with pytest.raises(ReviewValidationError, match=message):
            CandidateReviewService(session).review_candidate(
                extraction.candidate_id, ReviewDecision.APPROVE, "reviewer", overrides
            )
        assert (
            CandidateRepository(session).get(extraction.candidate_id).review_status
            is CandidateStatus.COLLECTED
        )
        assert session.scalar(select(func.count()).select_from(CandidateReviewModel)) == 0
    engine.dispose()


def test_optional_clear_reject_return_and_history_are_append_only(temp_settings: Settings) -> None:
    engine = create_collector_engine(temp_settings.database_url)
    initialize_database(engine)
    with session_scope(engine) as session:
        _, _, extraction = extracted_candidate(session, temp_settings)
        reviews = CandidateReviewService(session)
        approved = reviews.review_candidate(
            extraction.candidate_id,
            ReviewDecision.APPROVE,
            "reviewer",
            {"city": ""},
        )
        assert approved.resulting_status is CandidateStatus.APPROVED
        assert (
            reviews.review_candidate(
                extraction.candidate_id, ReviewDecision.REJECT, "reviewer", notes="not suitable"
            ).resulting_status
            is CandidateStatus.REJECTED
        )
        assert (
            reviews.review_candidate(
                extraction.candidate_id, ReviewDecision.RETURN_TO_REVIEW, "reviewer"
            ).resulting_status
            is CandidateStatus.NEEDS_REVIEW
        )
        history = reviews.history(extraction.candidate_id)
        assert [item.decision for item in history] == [
            ReviewDecision.APPROVE,
            ReviewDecision.REJECT,
            ReviewDecision.RETURN_TO_REVIEW,
        ]
        assert history[0].field_overrides == {"city": ""}
    engine.dispose()


def test_missing_core_conflict_warning_and_bad_cache_block_approval(
    temp_settings: Settings,
) -> None:
    engine = create_collector_engine(temp_settings.database_url)
    initialize_database(engine)
    with session_scope(engine) as session:
        _, source, extraction = extracted_candidate(session, temp_settings)
        candidate = session.get(CandidateModel, str(extraction.candidate_id))
        candidate.extraction_warnings = ["review this"]
        session.commit()
        with pytest.raises(ReviewValidationError, match="acknowledged"):
            CandidateReviewService(session).review_candidate(
                extraction.candidate_id, ReviewDecision.APPROVE, "reviewer"
            )
        Path(source.cached_file_path).write_bytes(b"corrupt")
        with pytest.raises(ReviewValidationError, match="hash"):
            CandidateReviewService(session).review_candidate(
                extraction.candidate_id,
                ReviewDecision.APPROVE,
                "reviewer",
                acknowledge_warnings=True,
            )
    engine.dispose()


def test_unresolved_conflict_blocks_approval(temp_settings: Settings) -> None:
    engine = create_collector_engine(temp_settings.database_url)
    initialize_database(engine)
    with session_scope(engine) as session:
        _, _, extraction = extracted_candidate(
            session, temp_settings, fixture="programme_conflict.html"
        )
        with pytest.raises(ReviewValidationError, match="unresolved conflicts"):
            CandidateReviewService(session).review_candidate(
                extraction.candidate_id,
                ReviewDecision.APPROVE,
                "reviewer",
                {"country_code": "DE"},
            )
        assert session.scalar(select(func.count()).select_from(CandidateReviewModel)) == 0
    engine.dispose()


def test_export_exact_contract_formula_safety_hashes_and_status(temp_settings: Settings) -> None:
    engine = create_collector_engine(temp_settings.database_url)
    initialize_database(engine)
    with session_scope(engine) as session:
        job, _, extraction = extracted_candidate(session, temp_settings)
        CandidateReviewService(session).review_candidate(
            extraction.candidate_id,
            ReviewDecision.APPROVE,
            "reviewer",
            {
                "program_name": "=SUM(A1:A2)",
                "city": "",
                "field_category": "Computer Science / IT",
            },
        )
        service = PathfinderExportService(temp_settings, session)
        dry = service.export_programs(job_id=job.id, dry_run=True)
        assert dry.exported_count == 1
        assert not dry.export_directory
        assert (
            CandidateRepository(session).get(extraction.candidate_id).review_status
            is CandidateStatus.APPROVED
        )
        result = service.export_programs(job_id=job.id, output_name="reviewed")
        assert result.exported_count == 1
        assert (
            CandidateRepository(session).get(extraction.candidate_id).review_status
            is CandidateStatus.EXPORTED
        )
        directory = result.export_directory
        with (directory / "programs.csv").open(newline="", encoding="utf-8") as handle:
            reader = csv.reader(handle)
            assert next(reader) == service.manifest.entity("programs").columns
            row = next(reader)
            assert row[2] == "'=SUM(A1:A2)"
            assert row[5] == ""
            assert row[8] == ""
            assert row[22] == "collected"
        with (directory / "source_records.csv").open(newline="", encoding="utf-8") as handle:
            reader = csv.reader(handle)
            assert next(reader) == service.manifest.entity("source_records").columns
            source_row = next(reader)
            assert "cache" not in ",".join(source_row).lower()
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        for filename, digest in manifest["files"].items():
            assert sha256_bytes((directory / filename).read_bytes()) == digest
        repeated = service.export_programs(candidate_ids=[extraction.candidate_id])
        assert repeated.exported_count == 1
    engine.dispose()


def test_export_skips_unapproved_and_blocks_duplicates(temp_settings: Settings) -> None:
    engine = create_collector_engine(temp_settings.database_url)
    initialize_database(engine)
    with session_scope(engine) as session:
        job, _, first = extracted_candidate(session, temp_settings)
        second_job, _, second = extracted_candidate(
            session, temp_settings, url="https://example.test/programme-2"
        )
        assert (
            PathfinderExportService(temp_settings, session)
            .export_programs(job_id=job.id, dry_run=True)
            .skipped_count
            == 1
        )
        reviewer = CandidateReviewService(session)
        reviewer.review_candidate(first.candidate_id, ReviewDecision.APPROVE, "reviewer")
        reviewer.review_candidate(second.candidate_id, ReviewDecision.APPROVE, "reviewer")
        combined = PathfinderExportService(temp_settings, session).export_programs(
            candidate_ids=[first.candidate_id, second.candidate_id], dry_run=True
        )
        assert combined.duplicate_groups
        assert combined.errors
        assert second_job.id != job.id
    engine.dispose()
