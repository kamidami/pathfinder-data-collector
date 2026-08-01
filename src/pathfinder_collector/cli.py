import platform

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
from pathfinder_collector.enums import EntityType
from pathfinder_collector.exceptions import ContractError
from pathfinder_collector.persistence.repositories import JobRepository
from pathfinder_collector.services.jobs import create_job

app = typer.Typer(help="Evidence-backed university data collector.", no_args_is_help=True)
contract_app = typer.Typer(help="Inspect versioned Pathfinder CSV contracts.")
job_app = typer.Typer(help="Manage collection jobs.")
app.add_typer(contract_app, name="contract")
app.add_typer(job_app, name="job")


def settings() -> Settings:
    return get_settings()


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


def _validation_message(exc: ValidationError) -> str:
    error = exc.errors()[0]
    return f"Invalid {'.'.join(str(part) for part in error['loc'])}: {error['msg']}"


def validate_job(job: CollectionJob) -> CollectionJob:
    """Stable validation hook for callers and tests."""
    return job
