from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from pathfinder_collector.persistence.models import Base


def create_collector_engine(database_url: str) -> Engine:
    if not database_url.startswith("sqlite:"):
        raise ValueError("the foundation supports collector-owned SQLite databases only")
    engine = create_engine(database_url)

    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection: object, _: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def initialize_database(engine: Engine) -> None:
    Base.metadata.create_all(engine)


def migrate_database(database_url: str, project_root: Path) -> None:
    """Upgrade collector schema using this repository's Alembic migrations."""
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")


def database_is_initialized(engine: Engine) -> bool:
    return "collection_jobs" in inspect(engine).get_table_names()


def database_file_exists(database_url: str) -> bool:
    if not database_url.startswith("sqlite:///"):
        return False
    path = database_url.removeprefix("sqlite:///")
    return path == ":memory:" or Path(path).is_file()


def check_connection(engine: Engine) -> None:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session:
        yield session
