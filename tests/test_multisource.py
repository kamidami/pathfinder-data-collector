import csv
from pathlib import Path

from sqlalchemy import func, select

from pathfinder_collector.config import Settings
from pathfinder_collector.database import (
    create_collector_engine,
    initialize_database,
    session_scope,
)
from pathfinder_collector.domain.evidence import EvidenceRecord, SourcePage
from pathfinder_collector.domain.jobs import CollectionJob
from pathfinder_collector.enums import (
    CandidateStatus,
    ConfidenceLevel,
    EntityType,
    FetchStatus,
    ReviewDecision,
    RobotsStatus,
    SourceType,
)
from pathfinder_collector.fetching.hashing import sha256_bytes
from pathfinder_collector.persistence.models import CandidateModel, ConflictModel, EvidenceModel
from pathfinder_collector.persistence.repositories import (
    CandidateRepository,
    ExtractionEvidenceRepository,
    JobRepository,
    SourcePageRepository,
)
from pathfinder_collector.services.blockers import (
    CandidateBlockerService,
    inaccessible_source_category,
)
from pathfinder_collector.services.exporting import PathfinderExportService
from pathfinder_collector.services.extraction import (
    ProgrammeExtractionService,
    agreement_confidence,
)
from pathfinder_collector.services.reports import CandidateReportService
from pathfinder_collector.services.review import CandidateReviewService

FIXTURES = Path(__file__).parent / "fixtures"


def add_source(session: object, settings: Settings, job: CollectionJob, fixture: str, url: str):
    content = (FIXTURES / fixture).read_bytes()
    path = settings.cache_dir / f"{fixture}-{len(url)}.html"
    path.write_bytes(content)
    return SourcePageRepository(session).save(
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
            cached_file_path=str(path),
        )
    )


def setup_multisource(session: object, settings: Settings, supporting_fixture: str):
    job = JobRepository(session).add(
        CollectionJob(
            name="multi", country_code="DE", entity_type=EntityType.PROGRAM, requested_limit=2
        )
    )
    primary = add_source(
        session, settings, job, "programme_labelled.html", "https://example.test/primary"
    )
    supporting = add_source(
        session, settings, job, supporting_fixture, "https://faculty.example.test/support?x=1"
    )
    service = ProgrammeExtractionService(
        JobRepository(session),
        SourcePageRepository(session),
        CandidateRepository(session),
        ExtractionEvidenceRepository(session),
    )
    first = service.extract_source(job.id, primary.id)
    second = service.extract_source(job.id, supporting.id, candidate_id=first.candidate_id)
    return job, primary, supporting, first, second, service


def test_supporting_source_is_idempotent_and_agreement_is_not_conflict(
    temp_settings: Settings,
) -> None:
    engine = create_collector_engine(temp_settings.database_url)
    initialize_database(engine)
    with session_scope(engine) as session:
        job, primary, supporting, first, second, service = setup_multisource(
            session, temp_settings, "programme_supporting_agreement.html"
        )
        count = session.scalar(select(func.count()).select_from(EvidenceModel))
        repeated = service.extract_source(job.id, supporting.id, candidate_id=first.candidate_id)
        assert repeated.candidate_id == first.candidate_id == second.candidate_id
        assert session.scalar(select(func.count()).select_from(CandidateModel)) == 1
        assert session.scalar(select(func.count()).select_from(EvidenceModel)) == count
        assert session.scalar(select(func.count()).select_from(ConflictModel)) == 0
        sources = CandidateRepository(session).sources_for(first.candidate_id)
        assert [(item.id, role) for item, role in sources] == [
            (primary.id, "primary"),
            (supporting.id, "supporting"),
        ]
        evidence_sources = {
            item.source_page_id
            for item in ExtractionEvidenceRepository(session).evidence_for(first.candidate_id)
        }
        assert evidence_sources == {primary.id, supporting.id}
    engine.dispose()


def test_disagreement_conflicts_and_confidence_upgrade_is_deterministic(
    temp_settings: Settings,
) -> None:
    medium = [
        EvidenceRecord(
            candidate_id="00000000-0000-0000-0000-000000000001",
            source_page_id=source_id,
            field_name="university_name",
            extracted_value="Example University",
            normalized_value="Example University",
            confidence=ConfidenceLevel.MEDIUM,
        )
        for source_id in (
            "00000000-0000-0000-0000-000000000002",
            "00000000-0000-0000-0000-000000000003",
        )
    ]
    assert agreement_confidence(medium) is ConfidenceLevel.HIGH
    engine = create_collector_engine(temp_settings.database_url)
    initialize_database(engine)
    with session_scope(engine) as session:
        _, _, _, first, _, _ = setup_multisource(
            session, temp_settings, "programme_supporting_conflict.html"
        )
        blockers = CandidateBlockerService(
            CandidateRepository(session), ExtractionEvidenceRepository(session)
        ).analyze(first.candidate_id)
        assert blockers.unresolved_conflicts == ["teaching_language"]
        assert blockers.categories == ["missing_teaching_language", "unresolved_conflict"]
        assert blockers.status is CandidateStatus.NEEDS_REVIEW
    engine.dispose()


def test_report_and_export_represent_multiple_sources_safely(temp_settings: Settings) -> None:
    engine = create_collector_engine(temp_settings.database_url)
    initialize_database(engine)
    with session_scope(engine) as session:
        job, _, _, first, _, _ = setup_multisource(
            session, temp_settings, "programme_supporting_agreement.html"
        )
        report_path = CandidateReportService(
            temp_settings,
            CandidateRepository(session),
            ExtractionEvidenceRepository(session),
            SourcePageRepository(session),
        ).generate(first.candidate_id)
        report = report_path.read_text(encoding="utf-8")
        assert "Primary:" in report and "Supporting:" in report
        assert "faculty.example.test/support" in report
        assert "agreement across official sources" in report
        assert "?x=1" not in report
        assert "<script" not in report
        CandidateReviewService(session).review_candidate(
            first.candidate_id,
            ReviewDecision.APPROVE,
            "reviewer",
            {"field_category": "Computer Science / IT"},
        )
        result = PathfinderExportService(temp_settings, session).export_programs(job_id=job.id)
        with (result.export_directory / "source_records.csv").open(
            encoding="utf-8", newline=""
        ) as handle:
            rows = list(csv.DictReader(handle))
        assert len(rows) == 2
        assert len({row["url"] for row in rows}) == 2
    engine.dispose()


def test_inaccessible_source_has_safe_controlled_category() -> None:
    source = SourcePage(
        job_id="00000000-0000-0000-0000-000000000001",
        original_url="https://example.test/blocked",
        normalized_url="https://example.test/blocked",
        source_type=SourceType.OFFICIAL_PROGRAM,
        official_domain=True,
        fetch_status=FetchStatus.HTTP_ERROR,
        robots_status=RobotsStatus.ALLOWED,
        http_status=403,
        error_code="http_403",
        safe_error_summary="request denied",
    )
    assert inaccessible_source_category(source) == "source_inaccessible"
