from pathlib import Path

import httpx

from pathfinder_collector.config import Settings
from pathfinder_collector.database import (
    create_collector_engine,
    initialize_database,
    session_scope,
)
from pathfinder_collector.domain.evidence import SourcePage
from pathfinder_collector.domain.jobs import CollectionJob
from pathfinder_collector.enums import (
    EntityType,
    FetchStatus,
    RobotsStatus,
    SourceType,
)
from pathfinder_collector.fetching.client import SafeHttpClient
from pathfinder_collector.fetching.hashing import sha256_bytes
from pathfinder_collector.persistence.repositories import JobRepository, SourcePageRepository


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


def test_source_fetch_and_list_cli(
    runner: object,
    cli_with_settings: object,
    temp_settings: Settings,
    monkeypatch: object,
) -> None:
    engine = create_collector_engine(temp_settings.database_url)
    initialize_database(engine)
    with session_scope(engine) as session:
        job = JobRepository(session).add(
            CollectionJob(
                name="source-cli",
                country_code="DE",
                entity_type=EntityType.PROGRAM,
                requested_limit=1,
            )
        )
    engine.dispose()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        return httpx.Response(200, headers={"content-type": "text/html"}, text="page")

    def mocked_client(config: Settings) -> SafeHttpClient:
        return SafeHttpClient(
            config,
            transport=httpx.MockTransport(handler),
            resolver=lambda host: ["93.184.216.34"],
            sleep=lambda seconds: None,
        )

    monkeypatch.setattr("pathfinder_collector.cli.fetch_client", mocked_client)
    fetched = runner.invoke(
        cli_with_settings,
        [
            "source",
            "fetch",
            "--job",
            str(job.id),
            "--url",
            "https://example.test/program?token=hidden",
            "--type",
            "official_program",
        ],
    )
    assert fetched.exit_code == 0, fetched.stdout
    assert "Status: fetched" in fetched.stdout
    assert "token=hidden" not in fetched.stdout
    listed = runner.invoke(cli_with_settings, ["source", "list", "--job", str(job.id)])
    assert listed.exit_code == 0
    assert "example.test/program" in listed.stdout
    assert "token=hidden" not in listed.stdout


def test_programme_extraction_and_candidate_cli(
    runner: object, cli_with_settings: object, temp_settings: Settings
) -> None:
    engine = create_collector_engine(temp_settings.database_url)
    initialize_database(engine)
    content = (Path(__file__).parent / "fixtures/programme_labelled.html").read_bytes()
    cache_path = temp_settings.cache_dir / "cli-programme.html"
    cache_path.write_bytes(content)
    with session_scope(engine) as session:
        job = JobRepository(session).add(
            CollectionJob(
                name="extract-cli",
                country_code="DE",
                entity_type=EntityType.PROGRAM,
                requested_limit=1,
            )
        )
        source = SourcePageRepository(session).save(
            SourcePage(
                job_id=job.id,
                original_url="https://example.test/programme?private=query",
                normalized_url="https://example.test/programme?private=query",
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
    engine.dispose()
    extracted = runner.invoke(
        cli_with_settings,
        ["program", "extract", "--job", str(job.id), "--source", str(source.id)],
    )
    assert extracted.exit_code == 0, extracted.stdout
    assert "Review status: collected" in extracted.stdout
    candidate_id = extracted.stdout.split("Candidate: ", 1)[1].splitlines()[0]
    listed = runner.invoke(cli_with_settings, ["candidate", "list", "--job", str(job.id)])
    assert listed.exit_code == 0
    assert "Data Science" in listed.stdout
    shown = runner.invoke(cli_with_settings, ["candidate", "show", candidate_id])
    assert shown.exit_code == 0
    assert "private=query" not in shown.stdout
    assert "Evidence confidence" in shown.stdout
    reported = runner.invoke(cli_with_settings, ["candidate", "report", candidate_id])
    assert reported.exit_code == 0
    assert "var" not in reported.stdout or "reports" in reported.stdout
