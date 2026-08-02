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
    ConflictResolutionAction,
    EntityType,
    FetchStatus,
    ReviewDecision,
    RobotsStatus,
    SourceType,
)
from pathfinder_collector.fetching.hashing import sha256_bytes
from pathfinder_collector.persistence.models import (
    CandidateContextModel,
    ConflictModel,
    ConflictResolutionModel,
    EvidenceModel,
    JobModel,
)
from pathfinder_collector.persistence.repositories import (
    CandidateRepository,
    ExtractionEvidenceRepository,
    JobRepository,
    SourcePageRepository,
)
from pathfinder_collector.services.blockers import CandidateBlockerService
from pathfinder_collector.services.conflicts import ConflictResolutionService
from pathfinder_collector.services.context import CandidateContextService
from pathfinder_collector.services.exporting import PathfinderExportService
from pathfinder_collector.services.extraction import ProgrammeExtractionService
from pathfinder_collector.services.reports import CandidateReportService
from pathfinder_collector.services.review import CandidateReviewService

FIXTURES = Path(__file__).parent / "fixtures"


def add_source(session: object, settings: Settings, job: CollectionJob, fixture: str, name: str):
    content = (FIXTURES / fixture).read_bytes()
    cache = settings.cache_dir / f"{name}.html"
    cache.write_bytes(content)
    source = SourcePageRepository(session).save(
        SourcePage(
            job_id=job.id,
            original_url=f"https://example.test/{name}",
            normalized_url=f"https://example.test/{name}",
            source_type=SourceType.OFFICIAL_PROGRAM,
            official_domain=True,
            fetch_status=FetchStatus.FETCHED,
            robots_status=RobotsStatus.ALLOWED,
            content_type="text/html",
            response_bytes=len(content),
            content_hash=sha256_bytes(content),
            cached_file_path=str(cache),
        )
    )
    return source, cache


def extraction_service(session: object) -> ProgrammeExtractionService:
    return ProgrammeExtractionService(
        JobRepository(session),
        SourcePageRepository(session),
        CandidateRepository(session),
        ExtractionEvidenceRepository(session),
    )


def candidate_without_country(session: object, settings: Settings):
    job = JobRepository(session).add(
        CollectionJob(
            name="context", country_code="DE", entity_type=EntityType.PROGRAM, requested_limit=2
        )
    )
    source, _ = add_source(session, settings, job, "programme_no_country.html", "primary")
    result = extraction_service(session).extract_source(job.id, source.id)
    return job, source, result


def candidate_with_city_conflict(session: object, settings: Settings):
    job = JobRepository(session).add(
        CollectionJob(
            name="conflict", country_code="DE", entity_type=EntityType.PROGRAM, requested_limit=2
        )
    )
    primary, _ = add_source(session, settings, job, "programme_labelled.html", "primary-city")
    supporting, supporting_cache = add_source(
        session, settings, job, "programme_city_munich.html", "support-city"
    )
    service = extraction_service(session)
    first = service.extract_source(job.id, primary.id)
    service.extract_source(job.id, supporting.id, candidate_id=first.candidate_id)
    return job, supporting, supporting_cache, first, service


def test_job_context_is_idempotent_separate_and_satisfies_country(temp_settings: Settings) -> None:
    engine = create_collector_engine(temp_settings.database_url)
    initialize_database(engine)
    with session_scope(engine) as session:
        _, _, result = candidate_without_country(session, temp_settings)
        evidence_before = session.scalar(select(func.count()).select_from(EvidenceModel))
        service = CandidateContextService(session)
        first = service.apply_job_country(result.candidate_id)
        second = service.apply_job_country(result.candidate_id)
        assert first.effective_country == second.effective_country == "DE"
        assert first.provenance == "operator_job_context"
        assert session.scalar(select(func.count()).select_from(CandidateContextModel)) == 1
        assert session.scalar(select(func.count()).select_from(EvidenceModel)) == evidence_before
        blockers = CandidateBlockerService(
            CandidateRepository(session), ExtractionEvidenceRepository(session)
        ).analyze(result.candidate_id)
        assert "country_code" not in blockers.missing_core_fields
    engine.dispose()


def test_invalid_job_country_and_source_contradiction_block_context(
    temp_settings: Settings,
) -> None:
    engine = create_collector_engine(temp_settings.database_url)
    initialize_database(engine)
    with session_scope(engine) as session:
        job, _, result = candidate_without_country(session, temp_settings)
        session.get(JobModel, str(job.id)).country_code = "D1"
        session.commit()
        with pytest.raises(ValueError, match="two ASCII"):
            CandidateContextService(session).apply_job_country(result.candidate_id)
        session.get(JobModel, str(job.id)).country_code = "DE"
        session.commit()
        CandidateContextService(session).apply_job_country(result.candidate_id)
        contradiction, _ = add_source(
            session, temp_settings, job, "programme_country_france.html", "france"
        )
        extraction_service(session).extract_source(
            job.id, contradiction.id, candidate_id=result.candidate_id
        )
        summary = CandidateContextService(session).summary(result.candidate_id)
        assert summary.effective_country is None
        assert summary.source_contradictions == ["FR"]
        blockers = CandidateBlockerService(
            CandidateRepository(session), ExtractionEvidenceRepository(session)
        ).analyze(result.candidate_id)
        assert "unresolved_conflict" in blockers.categories
    engine.dispose()


def test_conflict_resolution_audit_clear_and_reopen(temp_settings: Settings) -> None:
    engine = create_collector_engine(temp_settings.database_url)
    initialize_database(engine)
    with session_scope(engine) as session:
        job, supporting, cache, result, extractor = candidate_with_city_conflict(
            session, temp_settings
        )
        service = ConflictResolutionService(session)
        conflict = service.list_for_candidate(result.candidate_id)[0]
        evidence_before = session.scalar(select(func.count()).select_from(EvidenceModel))
        with pytest.raises(ValueError, match="note"):
            service.resolve(
                conflict.id,
                ConflictResolutionAction.CLEAR_OPTIONAL_FIELD,
                "reviewer",
                "",
            )
        resolved = service.resolve(
            conflict.id,
            ConflictResolutionAction.CLEAR_OPTIONAL_FIELD,
            "reviewer",
            "Locations differ across official programme pages; leave city blank.",
        )
        assert resolved.resolved_value == ""
        assert session.scalar(select(func.count()).select_from(EvidenceModel)) == evidence_before
        assert session.scalar(select(func.count()).select_from(ConflictResolutionModel)) == 1
        assert (
            "unresolved_conflict"
            not in CandidateBlockerService(
                CandidateRepository(session), ExtractionEvidenceRepository(session)
            )
            .analyze(result.candidate_id)
            .categories
        )
        extractor.extract_source(job.id, supporting.id, candidate_id=result.candidate_id)
        assert service.list_for_candidate(result.candidate_id)[0].status.value == "resolved"

        changed = (FIXTURES / "programme_city_hamburg.html").read_bytes()
        cache.write_bytes(changed)
        supporting.content_hash = sha256_bytes(changed)
        supporting.response_bytes = len(changed)
        SourcePageRepository(session).save(supporting)
        extractor.extract_source(job.id, supporting.id, candidate_id=result.candidate_id)
        reopened = service.list_for_candidate(result.candidate_id)[0]
        assert reopened.status.value == "unresolved"
        assert session.scalar(select(func.count()).select_from(ConflictResolutionModel)) == 1
    engine.dispose()


def test_core_conflict_cannot_be_cleared(temp_settings: Settings) -> None:
    engine = create_collector_engine(temp_settings.database_url)
    initialize_database(engine)
    with session_scope(engine) as session:
        job = JobRepository(session).add(
            CollectionJob(
                name="core", country_code="DE", entity_type=EntityType.PROGRAM, requested_limit=2
            )
        )
        source, _ = add_source(session, temp_settings, job, "programme_conflict.html", "core")
        result = extraction_service(session).extract_source(job.id, source.id)
        conflict = ConflictResolutionService(session).list_for_candidate(result.candidate_id)[0]
        with pytest.raises(ValueError, match="core fields"):
            ConflictResolutionService(session).resolve(
                conflict.id,
                ConflictResolutionAction.CLEAR_OPTIONAL_FIELD,
                "reviewer",
                "Core language cannot be blank.",
            )
    engine.dispose()


def test_report_and_export_record_context_provenance(temp_settings: Settings) -> None:
    engine = create_collector_engine(temp_settings.database_url)
    initialize_database(engine)
    with session_scope(engine) as session:
        job, _, result = candidate_without_country(session, temp_settings)
        CandidateContextService(session).apply_job_country(result.candidate_id)
        report = (
            CandidateReportService(
                temp_settings,
                CandidateRepository(session),
                ExtractionEvidenceRepository(session),
                SourcePageRepository(session),
            )
            .generate(result.candidate_id)
            .read_text(encoding="utf-8")
        )
        assert "provenance=job context" in report
        assert "Human-approved values are not verified" in report
        CandidateReviewService(session).review_candidate(
            result.candidate_id, ReviewDecision.APPROVE, "reviewer"
        )
        exported = PathfinderExportService(temp_settings, session).export_programs(job_id=job.id)
        manifest = json.loads((exported.export_directory / "manifest.json").read_text())
        assert manifest["field_provenance_counts"]["operator_job_context"] == 1
        with (exported.export_directory / "source_records.csv").open(
            encoding="utf-8", newline=""
        ) as handle:
            sources = list(csv.DictReader(handle))
        assert len(sources) == 1
        assert sources[0]["source_type"] == "official_program"
        with (exported.export_directory / "programs.csv").open(
            encoding="utf-8", newline=""
        ) as handle:
            programme = next(csv.DictReader(handle))
        assert programme["country_code"] == "DE"
        assert programme["data_status"] == "collected"
        assert session.scalar(select(func.count()).select_from(ConflictModel)) == 0
        assert (
            CandidateRepository(session).get(result.candidate_id).review_status
            is CandidateStatus.EXPORTED
        )
    engine.dispose()


def test_context_and_conflict_cli(
    temp_settings: Settings, runner: object, cli_with_settings: object
) -> None:
    engine = create_collector_engine(temp_settings.database_url)
    initialize_database(engine)
    with session_scope(engine) as session:
        _, _, context_candidate = candidate_without_country(session, temp_settings)
        _, _, _, conflict_candidate, _ = candidate_with_city_conflict(session, temp_settings)
        conflict_id = (
            ConflictResolutionService(session)
            .list_for_candidate(conflict_candidate.candidate_id)[0]
            .id
        )
    engine.dispose()
    context = runner.invoke(
        cli_with_settings,
        [
            "candidate",
            "context",
            str(context_candidate.candidate_id),
            "--apply-job-country",
        ],
    )
    assert context.exit_code == 0, context.stdout
    assert "Effective country: DE" in context.stdout
    assert "Provenance: job context" in context.stdout
    listed = runner.invoke(
        cli_with_settings,
        ["candidate", "conflict-list", str(conflict_candidate.candidate_id)],
    )
    assert listed.exit_code == 0, listed.stdout
    assert "city" in listed.stdout and "unresolved" in listed.stdout
    resolved = runner.invoke(
        cli_with_settings,
        [
            "candidate",
            "conflict-resolve",
            str(conflict_id),
            "--resolution",
            "clear-optional",
            "--reviewer",
            "reviewer",
            "--notes",
            "Official location evidence is ambiguous; leave optional city blank.",
        ],
    )
    assert resolved.exit_code == 0, resolved.stdout
    assert "Status: resolved" in resolved.stdout
