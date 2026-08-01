from pathlib import Path

from pathfinder_collector.config import Settings
from pathfinder_collector.database import create_collector_engine, initialize_database


def test_cli_help(runner: object, cli_with_settings: object) -> None:
    result = runner.invoke(cli_with_settings, ["--help"])
    assert result.exit_code == 0
    assert "doctor" in result.stdout


def test_doctor_command(runner: object, cli_with_settings: object) -> None:
    result = runner.invoke(cli_with_settings, ["doctor"])
    assert result.exit_code == 0
    assert "Configuration: OK" in result.stdout
    assert "Contract manifest: OK" in result.stdout


def test_init_db_command(
    runner: object, cli_with_settings: object, temp_settings: Settings
) -> None:
    project_root = Path(__file__).parents[1]
    temp_settings.project_root = project_root
    database_path = project_root / "var/test-cli.db"
    temp_settings.database_url = f"sqlite:///{database_path.as_posix()}"
    result = runner.invoke(cli_with_settings, ["init-db"])
    assert result.exit_code == 0, result.stdout
    database_path.unlink(missing_ok=True)


def test_job_creation_and_listing(
    runner: object, cli_with_settings: object, temp_settings: Settings
) -> None:
    engine = create_collector_engine(temp_settings.database_url)
    initialize_database(engine)
    engine.dispose()
    args = [
        "job",
        "create",
        "--name",
        "germany-g1",
        "--country",
        "DE",
        "--entity",
        "program",
        "--limit",
        "5",
    ]
    created = runner.invoke(cli_with_settings, args)
    assert created.exit_code == 0, created.stdout
    assert "Created pending job" in created.stdout
    listed = runner.invoke(cli_with_settings, ["job", "list"])
    assert listed.exit_code == 0
    assert "germany-g1" in listed.stdout


def test_job_creation_rejects_bad_country(
    runner: object, cli_with_settings: object, temp_settings: Settings
) -> None:
    engine = create_collector_engine(temp_settings.database_url)
    initialize_database(engine)
    engine.dispose()
    args = [
        "job",
        "create",
        "--name",
        "bad",
        "--country",
        "D1",
        "--entity",
        "program",
        "--limit",
        "5",
    ]
    result = runner.invoke(cli_with_settings, args)
    assert result.exit_code == 2
