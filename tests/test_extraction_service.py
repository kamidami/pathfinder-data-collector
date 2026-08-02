from pathlib import Path

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
    ConfidenceLevel,
    EntityType,
    ExtractionStatus,
    FetchStatus,
    RobotsStatus,
    SourceType,
)
from pathfinder_collector.extraction.evidence import suggestion
from pathfinder_collector.extraction.results import ExtractorOutput
from pathfinder_collector.fetching.hashing import sha256_bytes
from pathfinder_collector.persistence.models import CandidateModel, ConflictModel, EvidenceModel
from pathfinder_collector.persistence.repositories import (
    CandidateRepository,
    ExtractionEvidenceRepository,
    JobRepository,
    SourcePageRepository,
)
from pathfinder_collector.services.extraction import ProgrammeExtractionService
from pathfinder_collector.services.reports import CandidateReportService

FIXTURES = Path(__file__).parent / "fixtures"


def setup_source(
    session: object, settings: Settings, fixture: str, entity: EntityType = EntityType.PROGRAM
):
    jobs = JobRepository(session)
    job = jobs.add(
        CollectionJob(name="extract", country_code="DE", entity_type=entity, requested_limit=1)
    )
    content = (FIXTURES / fixture).read_bytes()
    cache_path = settings.cache_dir / f"{fixture}.html"
    cache_path.write_bytes(content)
    source = SourcePage(
        job_id=job.id,
        original_url="https://example.test/programme",
        normalized_url="https://example.test/programme",
        source_type=SourceType.OFFICIAL_PROGRAM,
        official_domain=True,
        fetch_status=FetchStatus.FETCHED,
        robots_status=RobotsStatus.ALLOWED,
        content_type="text/html",
        response_bytes=len(content),
        content_hash=sha256_bytes(content),
        cached_file_path=str(cache_path),
    )
    SourcePageRepository(session).save(source)
    return job, source, cache_path


def service(session: object) -> ProgrammeExtractionService:
    return ProgrammeExtractionService(
        JobRepository(session),
        SourcePageRepository(session),
        CandidateRepository(session),
        ExtractionEvidenceRepository(session),
    )


def test_complete_extraction_persists_candidate_and_evidence_idempotently(
    temp_settings: Settings,
) -> None:
    engine = create_collector_engine(temp_settings.database_url)
    initialize_database(engine)
    with session_scope(engine) as session:
        job, source, _ = setup_source(session, temp_settings, "programme_labelled.html")
        first = service(session).extract_source(job.id, source.id)
        second = service(session).extract_source(job.id, source.id)
        assert first.extraction_status is ExtractionStatus.EXTRACTED
        assert first.candidate_status is CandidateStatus.COLLECTED
        assert first.created_candidate
        assert second.updated_candidate
        assert second.candidate_id == first.candidate_id
        assert session.scalar(select(func.count()).select_from(CandidateModel)) == 1
        assert (
            session.scalar(select(func.count()).select_from(EvidenceModel)) == second.evidence_count
        )
        assert all(
            item.source_page_id == source.id
            for item in ExtractionEvidenceRepository(session).evidence_for(first.candidate_id)
        )
    engine.dispose()


def test_conflicting_language_creates_one_stable_conflict(temp_settings: Settings) -> None:
    engine = create_collector_engine(temp_settings.database_url)
    initialize_database(engine)
    with session_scope(engine) as session:
        job, source, _ = setup_source(session, temp_settings, "programme_conflict.html")
        first = service(session).extract_source(job.id, source.id)
        second = service(session).extract_source(job.id, source.id)
        assert first.candidate_status is CandidateStatus.NEEDS_REVIEW
        assert first.conflicts_count == 1
        assert second.conflicts_count == 1
        assert session.scalar(select(func.count()).select_from(ConflictModel)) == 1
        candidate = CandidateRepository(session).get(first.candidate_id)
        assert "teaching_language" not in candidate.normalized_data
    engine.dispose()


def test_missing_fields_and_low_confidence_require_review(temp_settings: Settings) -> None:
    engine = create_collector_engine(temp_settings.database_url)
    initialize_database(engine)
    with session_scope(engine) as session:
        job, source, _ = setup_source(session, temp_settings, "programme_missing.html")
        result = service(session).extract_source(job.id, source.id)
        assert result.extraction_status is ExtractionStatus.PARTIAL
        assert result.candidate_status is CandidateStatus.NEEDS_REVIEW
        assert "teaching_language" in result.fields_missing
    engine.dispose()


def test_source_validation_missing_and_corrupt_cache(temp_settings: Settings) -> None:
    engine = create_collector_engine(temp_settings.database_url)
    initialize_database(engine)
    with session_scope(engine) as session:
        job, source, cache_path = setup_source(session, temp_settings, "programme_labelled.html")
        cache_path.unlink()
        assert (
            service(session).extract_source(job.id, source.id).extraction_status
            is ExtractionStatus.CACHE_MISSING
        )
        cache_path.write_bytes(b"changed")
        assert (
            service(session).extract_source(job.id, source.id).extraction_status
            is ExtractionStatus.CACHE_CORRUPT
        )
        source.content_type = "application/pdf"
        SourcePageRepository(session).save(source)
        assert (
            service(session).extract_source(job.id, source.id).extraction_status
            is ExtractionStatus.UNSUPPORTED_SOURCE
        )
    engine.dispose()


def test_job_type_and_source_ownership_validation(temp_settings: Settings) -> None:
    engine = create_collector_engine(temp_settings.database_url)
    initialize_database(engine)
    with session_scope(engine) as session:
        scholarship_job, source, _ = setup_source(
            session, temp_settings, "programme_labelled.html", EntityType.SCHOLARSHIP
        )
        try:
            service(session).extract_source(scholarship_job.id, source.id)
        except ValueError as exc:
            assert "entity type" in str(exc)
        else:
            raise AssertionError("non-program job accepted")
        other_job = JobRepository(session).add(
            CollectionJob(
                name="other", country_code="DE", entity_type=EntityType.PROGRAM, requested_limit=1
            )
        )
        try:
            service(session).extract_source(other_job.id, source.id)
        except ValueError as exc:
            assert "belong" in str(exc)
        else:
            raise AssertionError("foreign source accepted")
    engine.dispose()


def test_non_programme_does_not_create_candidate(temp_settings: Settings) -> None:
    engine = create_collector_engine(temp_settings.database_url)
    initialize_database(engine)
    with session_scope(engine) as session:
        job, source, _ = setup_source(session, temp_settings, "non_programme.html")
        result = service(session).extract_source(job.id, source.id)
        assert result.extraction_status is ExtractionStatus.NO_PROGRAMME_DATA
        assert session.scalar(select(func.count()).select_from(CandidateModel)) == 0
    engine.dispose()


def test_low_confidence_value_not_normalized(temp_settings: Settings) -> None:
    class LowExtractor:
        def extract(self, content: bytes, source_url: str) -> ExtractorOutput:
            item = suggestion(
                "program_name",
                "Maybe Programme",
                "Maybe Programme",
                "weak context",
                ConfidenceLevel.LOW,
            )
            return ExtractorOutput(suggestions=[item], programme_context=True)

    engine = create_collector_engine(temp_settings.database_url)
    initialize_database(engine)
    with session_scope(engine) as session:
        job, source, _ = setup_source(session, temp_settings, "programme_missing.html")
        extractor_service = ProgrammeExtractionService(
            JobRepository(session),
            SourcePageRepository(session),
            CandidateRepository(session),
            ExtractionEvidenceRepository(session),
            LowExtractor(),
        )
        result = extractor_service.extract_source(job.id, source.id)
        candidate = CandidateRepository(session).get(result.candidate_id)
        assert candidate.review_status is CandidateStatus.NEEDS_REVIEW
        assert "program_name" not in candidate.normalized_data
    engine.dispose()


def test_report_escapes_values_and_does_not_embed_raw_page(temp_settings: Settings) -> None:
    engine = create_collector_engine(temp_settings.database_url)
    initialize_database(engine)
    with session_scope(engine) as session:
        job, source, _ = setup_source(session, temp_settings, "programme_missing.html")
        result = service(session).extract_source(job.id, source.id)
        path = CandidateReportService(
            temp_settings,
            CandidateRepository(session),
            ExtractionEvidenceRepository(session),
            SourcePageRepository(session),
        ).generate(result.candidate_id)
        report = path.read_text(encoding="utf-8")
        assert "Example &lt;University&gt;" in report
        assert "Example <University>" not in report
        assert "RAW_PAGE_MARKER" not in report
        assert "not verified" in report
        assert "<script" not in report
    engine.dispose()
