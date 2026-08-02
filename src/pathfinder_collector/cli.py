import json
import platform
from pathlib import Path
from uuid import UUID

import typer
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from pathfinder_collector.config import Settings, get_settings
from pathfinder_collector.contracts.pathfinder_v1 import load_manifest
from pathfinder_collector.database import (
    check_connection,
    create_collector_engine,
    database_file_exists,
    database_is_initialized,
    migrate_database,
    session_scope,
)
from pathfinder_collector.domain.jobs import CollectionJob
from pathfinder_collector.enums import EntityType, ReviewDecision, SourceType
from pathfinder_collector.exceptions import ContractError
from pathfinder_collector.fetching.client import SafeHttpClient
from pathfinder_collector.persistence.repositories import (
    CandidateRepository,
    ExtractionEvidenceRepository,
    JobRepository,
    SourcePageRepository,
)
from pathfinder_collector.services.exporting import (
    PathfinderExportService,
    duplicate_candidate_groups,
)
from pathfinder_collector.services.extraction import (
    SUPPORTED_FIELDS,
    ProgrammeExtractionService,
)
from pathfinder_collector.services.fetching import FetchService
from pathfinder_collector.services.jobs import create_job
from pathfinder_collector.services.reports import CandidateReportService
from pathfinder_collector.services.review import CandidateReviewService

app = typer.Typer(help="Evidence-backed university data collector.", no_args_is_help=True)
contract_app = typer.Typer(help="Inspect versioned Pathfinder CSV contracts.")
job_app = typer.Typer(help="Manage collection jobs.")
source_app = typer.Typer(help="Safely fetch and inspect official public sources.")
program_app = typer.Typer(help="Extract programme fields from fetched HTML.")
candidate_app = typer.Typer(help="Review extracted candidates and evidence.")
export_app = typer.Typer(help="Export explicitly approved records to Pathfinder v1 CSV.")
app.add_typer(contract_app, name="contract")
app.add_typer(job_app, name="job")
app.add_typer(source_app, name="source")
app.add_typer(program_app, name="program")
app.add_typer(candidate_app, name="candidate")
app.add_typer(export_app, name="export")


def settings() -> Settings:
    return get_settings()


def fetch_client(config: Settings) -> SafeHttpClient:
    return SafeHttpClient(config)


@app.command()
def doctor() -> None:
    """Check local configuration and collector resources without exposing secrets."""
    config = settings()
    typer.echo(f"Python: {platform.python_version()}")
    typer.echo("Configuration: OK")
    try:
        config.ensure_runtime_directories()
        typer.echo("Runtime directories: OK")
        load_manifest(config)
        typer.echo("Contract manifest: OK")
        if database_file_exists(config.database_url):
            engine = create_collector_engine(config.database_url)
            check_connection(engine)
            state = "initialized" if database_is_initialized(engine) else "not initialized"
            typer.echo(f"Database: reachable ({state})")
            engine.dispose()
        else:
            typer.echo("Database: not initialized")
    except (OSError, ValueError, ContractError, SQLAlchemyError) as exc:
        typer.echo(f"Doctor failed: {exc}", err=True)
        raise typer.Exit(1) from exc


@app.command("init-db")
def init_db() -> None:
    """Initialize the collector-owned SQLite database."""
    config = settings()
    config.ensure_runtime_directories()
    migrate_database(config.database_url, config.project_root)
    typer.echo("Collector database initialized.")


@contract_app.command("list")
def contract_list() -> None:
    manifest = load_manifest(settings())
    for entity in manifest.entities:
        typer.echo(f"{entity.entity_type}: {entity.template}")


@contract_app.command("show")
def contract_show(entity_name: str) -> None:
    try:
        entity = load_manifest(settings()).entity(entity_name)
    except ContractError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    typer.echo(f"Contract v1 / {entity.entity_type}")
    for index, column in enumerate(entity.columns, start=1):
        typer.echo(f"{index:>2}. {column}")


@job_app.command("create")
def job_create(
    name: str = typer.Option(..., help="Human-readable job name."),
    country: str = typer.Option(..., help="Two-letter country code."),
    entity: EntityType = typer.Option(..., help="Entity type."),
    limit: int = typer.Option(..., help="Positive requested record limit."),
) -> None:
    config = settings()
    engine = create_collector_engine(config.database_url)
    if not database_is_initialized(engine):
        engine.dispose()
        typer.echo("Database is not initialized; run init-db first.", err=True)
        raise typer.Exit(1)
    try:
        with session_scope(engine) as session:
            job = create_job(
                JobRepository(session),
                name=name,
                country_code=country,
                entity_type=entity,
                requested_limit=limit,
            )
    except ValidationError as exc:
        typer.echo(_validation_message(exc), err=True)
        raise typer.Exit(2) from exc
    finally:
        engine.dispose()
    typer.echo(f"Created pending job {job.id} ({job.name}, {job.country_code}, {job.entity_type}).")


@job_app.command("list")
def job_list() -> None:
    config = settings()
    engine = create_collector_engine(config.database_url)
    if not database_is_initialized(engine):
        engine.dispose()
        typer.echo("Database is not initialized; run init-db first.", err=True)
        raise typer.Exit(1)
    with session_scope(engine) as session:
        jobs = JobRepository(session).list()
    engine.dispose()
    if not jobs:
        typer.echo("No collection jobs.")
        return
    for job in jobs:
        typer.echo(
            f"{job.id}  {job.status.value:<9}  {job.country_code}  "
            f"{job.entity_type.value:<14}  {job.requested_limit:>4}  {job.name}"
        )


@source_app.command("fetch")
def source_fetch(
    job: UUID = typer.Option(..., help="Collection job UUID."),
    url: str = typer.Option(..., help="Official public HTTP(S) URL."),
    source_type: SourceType = typer.Option(..., "--type", help="Controlled source type."),
    force_refresh: bool = typer.Option(False, help="Bypass a valid page cache entry."),
) -> None:
    config = settings()
    engine = create_collector_engine(config.database_url)
    client = fetch_client(config)
    try:
        with session_scope(engine) as session:
            service = FetchService(
                config, JobRepository(session), SourcePageRepository(session), client
            )
            result = service.fetch_url(job, url, source_type, force_refresh=force_refresh)
    except ValueError as exc:
        typer.echo(f"Fetch rejected: {exc}", err=True)
        raise typer.Exit(2) from exc
    finally:
        client.close()
        engine.dispose()
    hash_prefix = result.content_hash[:12] if result.content_hash else "-"
    typer.echo(f"Source: {result.source_page_id}")
    typer.echo(f"URL: {result.safe_display_url or '(invalid URL)'}")
    typer.echo(f"Status: {result.status.value}")
    typer.echo(f"HTTP: {result.http_status or '-'}  Type: {result.content_type or '-'}")
    typer.echo(f"Bytes: {result.response_bytes}  Robots: {result.robots_status.value}")
    typer.echo(f"Cache hit: {'yes' if result.cache_hit else 'no'}  Hash: {hash_prefix}")
    if result.safe_error_code:
        typer.echo(f"Review: {result.safe_error_code} - {result.safe_error_summary}")


@source_app.command("list")
def source_list(job: UUID = typer.Option(..., help="Collection job UUID.")) -> None:
    config = settings()
    engine = create_collector_engine(config.database_url)
    try:
        with session_scope(engine) as session:
            repository = SourcePageRepository(session)
            if not JobRepository(session).exists(job):
                raise ValueError("collection job does not exist")
            pages = repository.list_for_job(job)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    finally:
        engine.dispose()
    if not pages:
        typer.echo("No source pages.")
        return
    for page in pages:
        safe_url = str(page.normalized_url).split("?", 1)[0]
        typer.echo(
            f"{page.id}  {page.fetch_status.value:<22}  {page.robots_status.value:<11}  {safe_url}"
        )


@program_app.command("extract")
def program_extract(
    job: UUID = typer.Option(..., help="Programme collection job UUID."),
    source: UUID = typer.Option(..., help="Fetched source-page UUID."),
    force: bool = typer.Option(False, help="Re-run deterministic extraction."),
    candidate: UUID | None = typer.Option(
        None, help="Existing candidate UUID when this is an official supporting page."
    ),
) -> None:
    config = settings()
    engine = create_collector_engine(config.database_url)
    try:
        with session_scope(engine) as session:
            result = ProgrammeExtractionService(
                JobRepository(session),
                SourcePageRepository(session),
                CandidateRepository(session),
                ExtractionEvidenceRepository(session),
            ).extract_source(job, source, force=force, candidate_id=candidate)
    except ValueError as exc:
        typer.echo(f"Extraction rejected: {exc}", err=True)
        raise typer.Exit(2) from exc
    finally:
        engine.dispose()
    typer.echo(f"Candidate: {result.candidate_id or '-'}")
    typer.echo(f"Extraction: {result.extraction_status.value}")
    typer.echo(
        f"Review status: {result.candidate_status.value if result.candidate_status else '-'}"
    )
    typer.echo(f"Fields found: {', '.join(result.fields_found) or '-'}")
    typer.echo(f"Fields missing: {', '.join(result.fields_missing) or '-'}")
    typer.echo(f"Evidence: {result.evidence_count}  Conflicts: {result.conflicts_count}")
    for warning in result.warnings[:10]:
        typer.echo(f"Warning: {warning}")


@candidate_app.command("list")
def candidate_list(job: UUID = typer.Option(..., help="Collection job UUID.")) -> None:
    config = settings()
    engine = create_collector_engine(config.database_url)
    try:
        with session_scope(engine) as session:
            if not JobRepository(session).exists(job):
                raise ValueError("collection job does not exist")
            candidates = CandidateRepository(session).list_for_job(job)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    finally:
        engine.dispose()
    if not candidates:
        typer.echo("No candidates.")
        return
    for candidate in candidates:
        name = candidate.normalized_data.get("program_name", "(unnamed)")
        typer.echo(f"{candidate.id}  {candidate.review_status.value:<12}  {name}")


@candidate_app.command("show")
def candidate_show(candidate_id: UUID) -> None:
    config = settings()
    engine = create_collector_engine(config.database_url)
    try:
        with session_scope(engine) as session:
            candidate = CandidateRepository(session).get(candidate_id)
            if candidate is None:
                raise ValueError("candidate does not exist")
            evidence_repo = ExtractionEvidenceRepository(session)
            evidence = evidence_repo.evidence_for(candidate_id)
            conflicts = evidence_repo.conflicts_for(candidate_id)
            source = next(
                (
                    item
                    for item in SourcePageRepository(session).list_for_job(candidate.job_id)
                    if item.id == candidate.source_page_id
                ),
                None,
            )
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    finally:
        engine.dispose()
    typer.echo(f"Candidate: {candidate.id}")
    typer.echo(f"Status: {candidate.review_status.value}")
    if source:
        typer.echo(f"Source: {str(source.normalized_url).split('?', 1)[0]}")
    for key, value in sorted(candidate.normalized_data.items()):
        typer.echo(f"{key}: {value}")
    missing = sorted(SUPPORTED_FIELDS - set(candidate.normalized_data))
    typer.echo(f"Missing: {', '.join(missing) or '-'}")
    confidence = {level: 0 for level in ("high", "medium", "low")}
    for item in evidence:
        confidence[item.confidence.value] += 1
    typer.echo(
        "Evidence confidence: "
        + ", ".join(f"{level}={count}" for level, count in confidence.items())
    )
    typer.echo(f"Conflicts: {', '.join(item.field_name for item in conflicts) or '-'}")


@candidate_app.command("report")
def candidate_report(candidate_id: UUID) -> None:
    config = settings()
    engine = create_collector_engine(config.database_url)
    try:
        with session_scope(engine) as session:
            path = CandidateReportService(
                config,
                CandidateRepository(session),
                ExtractionEvidenceRepository(session),
                SourcePageRepository(session),
            ).generate(candidate_id)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    finally:
        engine.dispose()
    typer.echo(f"Report: {path.relative_to(config.project_root)}")


@candidate_app.command("review")
def candidate_review(
    candidate_id: UUID,
    decision: ReviewDecision = typer.Option(..., help="Explicit human decision."),
    reviewer: str = typer.Option(..., help="Short local operator label."),
    notes: str | None = typer.Option(None, help="Bounded plain-text review note."),
    overrides: Path | None = typer.Option(None, help="Local JSON field override file."),
    acknowledge_warnings: bool = typer.Option(False, help="Acknowledge non-blocking warnings."),
) -> None:
    config = settings()
    override_values = _load_override_file(overrides, config) if overrides else {}
    engine = create_collector_engine(config.database_url)
    try:
        with session_scope(engine) as session:
            review = CandidateReviewService(session).review_candidate(
                candidate_id,
                decision,
                reviewer,
                override_values,
                notes,
                acknowledge_warnings,
            )
    except ValueError as exc:
        typer.echo(f"Review rejected: {exc}", err=True)
        raise typer.Exit(2) from exc
    finally:
        engine.dispose()
    typer.echo(f"Decision: {review.decision.value}")
    typer.echo(f"Candidate: {review.candidate_id}")
    typer.echo(f"Resulting status: {review.resulting_status.value}")
    typer.echo(f"Changed fields: {', '.join(review.field_overrides) or 'none'}")


@candidate_app.command("history")
def candidate_history(candidate_id: UUID) -> None:
    config = settings()
    engine = create_collector_engine(config.database_url)
    try:
        with session_scope(engine) as session:
            history = CandidateReviewService(session).history(candidate_id)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    finally:
        engine.dispose()
    if not history:
        typer.echo("No review history.")
        return
    for item in history:
        fields = ",".join(item.field_overrides) or "-"
        typer.echo(
            f"{item.reviewed_at.isoformat()}  {item.decision.value:<16}  "
            f"{item.reviewer_label:<12}  {item.resulting_status.value:<12}  "
            f"fields={fields}  notes={item.review_notes or '-'}"
        )


@candidate_app.command("duplicates")
def candidate_duplicates(job: UUID = typer.Option(..., help="Collection job UUID.")) -> None:
    from sqlalchemy import select

    from pathfinder_collector.persistence.models import CandidateModel

    config = settings()
    engine = create_collector_engine(config.database_url)
    try:
        with session_scope(engine) as session:
            if not JobRepository(session).exists(job):
                raise ValueError("collection job does not exist")
            candidates = list(
                session.scalars(
                    select(CandidateModel).where(CandidateModel.job_id == str(job))
                ).all()
            )
            groups = duplicate_candidate_groups(candidates, session)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    finally:
        engine.dispose()
    if not groups:
        typer.echo("No exact programme duplicates.")
        return
    for index, group in enumerate(groups, start=1):
        typer.echo(f"Duplicate group {index}: {', '.join(item.id for item in group)}")


@candidate_app.command("blockers")
def candidate_blockers(candidate_id: UUID) -> None:
    from pathfinder_collector.services.blockers import CandidateBlockerService

    config = settings()
    engine = create_collector_engine(config.database_url)
    try:
        with session_scope(engine) as session:
            result = CandidateBlockerService(
                CandidateRepository(session), ExtractionEvidenceRepository(session)
            ).analyze(candidate_id)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    finally:
        engine.dispose()
    typer.echo(f"Candidate: {result.candidate_id}")
    typer.echo(f"Status: {result.status.value}")
    typer.echo(f"Missing core: {', '.join(result.missing_core_fields) or '-'}")
    typer.echo(f"Low-confidence core: {', '.join(result.low_confidence_core_fields) or '-'}")
    typer.echo(f"Conflicts: {', '.join(result.unresolved_conflicts) or '-'}")
    typer.echo(f"Warnings: {len(result.warnings)}")
    typer.echo(f"Source integrity: {result.source_integrity}")
    typer.echo(f"Export eligible: {'yes' if result.export_eligible else 'no'}")
    typer.echo(f"Blockers: {', '.join(result.categories) or '-'}")


@candidate_app.command("context")
def candidate_context(
    candidate_id: UUID,
    apply_job_country: bool = typer.Option(
        False, help="Explicitly apply the candidate job's country context."
    ),
) -> None:
    from pathfinder_collector.services.context import CandidateContextService

    config = settings()
    engine = create_collector_engine(config.database_url)
    try:
        with session_scope(engine) as session:
            service = CandidateContextService(session)
            result = (
                service.apply_job_country(candidate_id)
                if apply_job_country
                else service.summary(candidate_id)
            )
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    finally:
        engine.dispose()
    typer.echo(f"Candidate: {result.candidate_id}")
    typer.echo(f"Job country: {result.job_country}")
    typer.echo(f"Effective country: {result.effective_country or '-'}")
    provenance = "job context" if result.provenance == "operator_job_context" else "-"
    typer.echo(f"Provenance: {provenance}")
    typer.echo(f"Source contradictions: {', '.join(result.source_contradictions) or '-'}")
    typer.echo(f"Approval eligible: {'yes' if result.approval_eligible else 'no'}")


@candidate_app.command("conflict-list")
def candidate_conflict_list(candidate_id: UUID) -> None:
    from pathfinder_collector.services.conflicts import ConflictResolutionService

    config = settings()
    engine = create_collector_engine(config.database_url)
    try:
        with session_scope(engine) as session:
            items = ConflictResolutionService(session).list_for_candidate(candidate_id)
    finally:
        engine.dispose()
    if not items:
        typer.echo("No evidence conflicts.")
        return
    for item in items:
        typer.echo(
            f"{item.id}  {item.field_name}  {item.status.value}  "
            f"first={item.first_value[:120]}  second={item.second_value[:120]}  "
            f"selected={(item.resolved_value or '-')[:120]}"
        )


@candidate_app.command("conflict-resolve")
def candidate_conflict_resolve(
    conflict_id: UUID,
    resolution: str = typer.Option(..., help="Controlled conflict resolution."),
    reviewer: str = typer.Option(..., help="Short local operator label."),
    notes: str = typer.Option(..., help="Required bounded resolution reason."),
    overrides: Path | None = typer.Option(None, help="Controlled JSON override file."),
) -> None:
    from pathfinder_collector.enums import ConflictResolutionAction
    from pathfinder_collector.services.conflicts import ConflictResolutionService

    aliases = {
        "select-first": "select_first",
        "select-second": "select_second",
        "clear-optional": "clear_optional_field",
        "override": "reviewer_override",
        "keep-unresolved": "keep_unresolved",
    }
    try:
        action = ConflictResolutionAction(aliases.get(resolution, resolution))
    except ValueError as exc:
        typer.echo("unsupported conflict resolution", err=True)
        raise typer.Exit(2) from exc
    config = settings()
    override_values = _load_override_file(overrides, config) if overrides else {}
    engine = create_collector_engine(config.database_url)
    try:
        with session_scope(engine) as session:
            result = ConflictResolutionService(session).resolve(
                conflict_id, action, reviewer, notes, override_values
            )
    except ValueError as exc:
        typer.echo(f"Conflict resolution rejected: {exc}", err=True)
        raise typer.Exit(2) from exc
    finally:
        engine.dispose()
    typer.echo(f"Conflict: {result.id}")
    typer.echo(f"Field: {result.field_name}")
    typer.echo(f"Status: {result.status.value}")
    typer.echo(f"Selected: {result.resolved_value if result.resolved_value is not None else '-'}")


@candidate_app.command("review-interactive")
def candidate_review_interactive(candidate_id: UUID) -> None:
    config = settings()
    engine = create_collector_engine(config.database_url)
    try:
        with session_scope(engine) as session:
            candidate = CandidateRepository(session).get(candidate_id)
            if candidate is None:
                raise ValueError("candidate does not exist")
            evidence_repo = ExtractionEvidenceRepository(session)
            conflicts = evidence_repo.conflicts_for(candidate_id)
            evidence = evidence_repo.evidence_for(candidate_id)
        effective = {**candidate.normalized_data, **candidate.reviewer_overrides}
        typer.echo(f"Candidate {candidate.id} ({candidate.review_status.value})")
        for key, value in sorted(effective.items()):
            typer.echo(f"  {key}: {value}")
        typer.echo(f"Conflicts: {', '.join(item.field_name for item in conflicts) or '-'}")
        for item in evidence[:30]:
            typer.echo(
                f"  evidence {item.field_name} [{item.confidence.value}]: "
                f"{item.short_evidence_text}"
            )
        decision = ReviewDecision(typer.prompt("Decision (approve/reject/return_to_review)"))
        reviewer = typer.prompt("Reviewer label")
        notes = typer.prompt("Review notes (optional)", default="", show_default=False)
        raw = typer.prompt("Override JSON object (optional)", default="{}", show_default=False)
        if len(raw.encode("utf-8")) > 64 * 1024:
            raise ValueError("override JSON is too large")
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("override JSON must be an object")
        acknowledge = False
        if candidate.extraction_warnings:
            acknowledge = typer.confirm("Acknowledge extraction warnings?", default=False)
        if decision is ReviewDecision.APPROVE and not typer.confirm(
            "Confirm explicit human approval?", default=False
        ):
            typer.echo("Cancelled; no changes saved.")
            return
        with session_scope(engine) as session:
            review = CandidateReviewService(session).review_candidate(
                candidate_id, decision, reviewer, parsed, notes, acknowledge
            )
        typer.echo(f"Saved {review.decision.value}; status={review.resulting_status.value}")
    except (ValueError, json.JSONDecodeError) as exc:
        typer.echo(f"Interactive review cancelled: {exc}", err=True)
        raise typer.Exit(2) from exc
    except (KeyboardInterrupt, typer.Abort):
        typer.echo("Cancelled; no changes saved.")
        raise typer.Exit(1) from None
    finally:
        engine.dispose()


@export_app.command("programs")
def export_programs(
    job: UUID | None = typer.Option(None, help="Collection job UUID."),
    candidate: list[UUID] | None = typer.Option(None, help="Candidate UUID; repeatable."),
    name: str | None = typer.Option(None, help="Safe descriptive export label."),
    dry_run: bool = typer.Option(False, help="Validate without files or state changes."),
) -> None:
    config = settings()
    engine = create_collector_engine(config.database_url)
    try:
        with session_scope(engine) as session:
            result = PathfinderExportService(config, session).export_programs(
                candidate_ids=candidate, job_id=job, output_name=name, dry_run=dry_run
            )
    except ValueError as exc:
        typer.echo(f"Export rejected: {exc}", err=True)
        raise typer.Exit(2) from exc
    finally:
        engine.dispose()
    typer.echo(f"Export run: {result.export_run_id}")
    typer.echo(f"Approved selected: {result.approved_selected}")
    typer.echo(f"Exported: {result.exported_count}  Skipped: {result.skipped_count}")
    for warning in result.warnings:
        typer.echo(f"Warning: {warning}")
    for error in result.errors:
        typer.echo(f"Error: {error}")
    if result.export_directory:
        typer.echo(f"Directory: {result.export_directory.relative_to(config.project_root)}")
    for filename, digest in sorted(result.file_hashes.items()):
        typer.echo(f"{filename}: {digest}")
    if result.errors:
        raise typer.Exit(2)


@export_app.command("show")
def export_show(export_run_id: UUID) -> None:
    config = settings()
    engine = create_collector_engine(config.database_url)
    try:
        with session_scope(engine) as session:
            run, files = PathfinderExportService(config, session).show(export_run_id)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    finally:
        engine.dispose()
    typer.echo(f"Export run: {run.id}")
    typer.echo(f"Status: {run.status}  Records: {run.record_count}")
    typer.echo(f"Directory: {run.export_path}")
    for item in files:
        typer.echo(f"{item.filename}: {item.sha256}")


def _load_override_file(path: Path, config: Settings) -> dict[str, object]:
    resolved = path.resolve()
    try:
        resolved.relative_to(config.project_root)
    except ValueError as exc:
        raise typer.BadParameter("override file must be within the project directory") from exc
    if resolved.suffix.lower() != ".json" or not resolved.is_file():
        raise typer.BadParameter("override file must be an existing JSON file")
    if resolved.stat().st_size > 64 * 1024:
        raise typer.BadParameter("override JSON exceeds 64 KiB")
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise typer.BadParameter("override file is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise typer.BadParameter("override JSON must contain one object")
    return payload


def _validation_message(exc: ValidationError) -> str:
    error = exc.errors()[0]
    return f"Invalid {'.'.join(str(part) for part in error['loc'])}: {error['msg']}"


def validate_job(job: CollectionJob) -> CollectionJob:
    """Stable validation hook for callers and tests."""
    return job
