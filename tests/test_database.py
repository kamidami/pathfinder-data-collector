import pytest
from sqlalchemy import text

from pathfinder_collector.config import Settings
from pathfinder_collector.database import (
    create_collector_engine,
    initialize_database,
    session_scope,
)
from pathfinder_collector.domain.jobs import CollectionJob
from pathfinder_collector.enums import EntityType
from pathfinder_collector.persistence.repositories import JobRepository


def test_database_initialization_and_foreign_keys(temp_settings: Settings) -> None:
    engine = create_collector_engine(temp_settings.database_url)
    initialize_database(engine)
    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
        tables = connection.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'")
        ).scalars()
        assert "collection_jobs" in set(tables)
    engine.dispose()


def test_job_repository_create_and_list(temp_settings: Settings) -> None:
    engine = create_collector_engine(temp_settings.database_url)
    initialize_database(engine)
    job = CollectionJob(
        name="germany", country_code="DE", entity_type=EntityType.PROGRAM, requested_limit=5
    )
    with session_scope(engine) as session:
        repository = JobRepository(session)
        repository.add(job)
        found = repository.list()
    assert found == [job]
    engine.dispose()


def test_non_sqlite_database_is_rejected() -> None:
    with pytest.raises(ValueError, match="SQLite"):
        create_collector_engine("postgresql://pathfinder.example/db")
