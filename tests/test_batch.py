import csv
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from pathfinder_collector.database import create_collector_engine, initialize_database
from pathfinder_collector.enums import (
    CandidateStatus,
    EntityType,
    ExtractionStatus,
    FetchStatus,
    RobotsStatus,
)
from pathfinder_collector.extraction.results import ProgrammeExtractionResult
from pathfinder_collector.fetching.results import FetchResult
from pathfinder_collector.services.batch import (
    BatchCollectionService,
    BatchValidationError,
    canonicalize_url,
    read_batch_csv,
)


def write_csv(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


class Jobs:
    def __init__(self, job: object | None) -> None:
        self.job = job

    def get(self, _job_id: object) -> object | None:
        return self.job


class Sources:
    def __init__(self, pages: list[object] | None = None) -> None:
        self.pages = pages or []

    def list_for_job(self, _job_id: object) -> list[object]:
        return self.pages


class Candidates:
    def __init__(self, candidate: object | None = None) -> None:
        self.candidate = candidate

    def find_by_source(self, _job_id: object, _source_id: object) -> object | None:
        return self.candidate


class Fetcher:
    def __init__(self, statuses: list[tuple[FetchStatus, int | None]]) -> None:
        self.statuses = statuses
        self.urls: list[str] = []

    def fetch_url(self, _job_id: object, url: str, _source_type: object) -> FetchResult:
        self.urls.append(url)
        status, http = self.statuses.pop(0)
        return FetchResult(
            source_page_id=uuid4(),
            requested_url=url,
            final_normalized_url=url,
            status=status,
            http_status=http,
            robots_status=(
                RobotsStatus.DISALLOWED
                if status is FetchStatus.ROBOTS_DISALLOWED
                else RobotsStatus.ALLOWED
            ),
            safe_error_summary="blocked" if status is not FetchStatus.FETCHED else None,
        )


class Extractor:
    def __init__(self, official_name: str = "Official University") -> None:
        self.official_name = official_name
        self.calls = 0

    def extract_source(self, _job_id: object, source_id: object) -> ProgrammeExtractionResult:
        self.calls += 1
        return ProgrammeExtractionResult(
            source_page_id=source_id,
            candidate_id=uuid4(),
            extraction_status=ExtractionStatus.PARTIAL,
            candidate_status=CandidateStatus.NEEDS_REVIEW,
            created_candidate=True,
        )


DEFAULT_JOB = object()


def service(temp_settings, fetcher, extractor, *, job=DEFAULT_JOB, pages=None, candidate=None):
    selected_job = SimpleNamespace(entity_type=EntityType.PROGRAM) if job is DEFAULT_JOB else job
    return BatchCollectionService(
        temp_settings,
        Jobs(selected_job),
        Sources(pages),
        Candidates(candidate),
        fetcher,
        extractor,
    )


def test_valid_multi_row_batch_and_reports(temp_settings, tmp_path: Path) -> None:
    path = write_csv(
        tmp_path / "batch.csv",
        "source_url,expected_university_name\nhttps://one.example/a,=Hint\nhttps://two.example/b,Two\n",
    )
    fetcher = Fetcher([(FetchStatus.FETCHED, 200), (FetchStatus.FETCHED, 200)])
    result = service(temp_settings, fetcher, Extractor()).collect(uuid4(), path)
    assert result.successful_fetches == result.extraction_successes == 2
    assert result.candidates_created == 2
    assert result.needs_review_count == 2
    summary = (result.report_directory / "batch_summary.json").read_text(encoding="utf-8")
    assert "raw HTML" not in summary and "cache_path" not in summary
    rows = list(
        csv.DictReader(
            (result.report_directory / "batch_results.csv").open(encoding="utf-8", newline="")
        )
    )
    assert rows[0]["expected_university_name"] == "'=Hint"
    assert json.loads(summary)["collector_version"]


def test_duplicate_and_canonical_duplicate_are_skipped(tmp_path: Path) -> None:
    path = write_csv(
        tmp_path / "batch.csv",
        "source_url\nHTTPS://EXAMPLE.COM:443/a#x\nhttps://example.com/a\n",
    )
    rows, count, duplicates = read_batch_csv(path)
    assert (len(rows), count, duplicates) == (1, 2, 1)
    assert rows[0].canonical_url == "https://example.com/a"


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("other\nx\n", "missing required source_url header"),
        ("source_url\nftp://example.com/x\n", "row 2"),
        ("source_url\nnot-a-url\n", "row 2"),
        ("source_url,extra\nhttps://example.com,x\n", "unknown input columns"),
    ],
)
def test_input_validation(content: str, message: str, tmp_path: Path) -> None:
    with pytest.raises(BatchValidationError, match=message):
        read_batch_csv(write_csv(tmp_path / "bad.csv", content))


def test_missing_and_wrong_job_fail_before_fetch(temp_settings, tmp_path: Path) -> None:
    path = write_csv(tmp_path / "batch.csv", "source_url\nhttps://example.com/a\n")
    fetcher = Fetcher([])
    with pytest.raises(BatchValidationError, match="does not exist"):
        service(temp_settings, fetcher, Extractor(), job=None).collect(uuid4(), path)
    wrong = SimpleNamespace(entity_type=EntityType.SCHOLARSHIP)
    with pytest.raises(BatchValidationError, match="must be program"):
        service(temp_settings, fetcher, Extractor(), job=wrong).collect(uuid4(), path)
    assert fetcher.urls == []


def test_existing_url_is_idempotent(temp_settings, tmp_path: Path) -> None:
    path = write_csv(tmp_path / "batch.csv", "source_url\nhttps://example.com/a\n")
    source_id = uuid4()
    page = SimpleNamespace(
        id=source_id,
        original_url="https://example.com/a",
        normalized_url="https://example.com/a",
        fetch_status=FetchStatus.FETCHED,
        http_status=200,
    )
    candidate = SimpleNamespace(id=uuid4(), review_status=CandidateStatus.NEEDS_REVIEW)
    fetcher = Fetcher([])
    result = service(
        temp_settings, fetcher, Extractor(), pages=[page], candidate=candidate
    ).collect(uuid4(), path)
    assert result.already_existing_urls == result.candidates_reused == 1
    assert fetcher.urls == []


def test_failures_continue_and_are_not_bypassed(temp_settings, tmp_path: Path) -> None:
    path = write_csv(
        tmp_path / "batch.csv",
        "source_url\nhttps://one.example/a\nhttps://two.example/b\nhttps://three.example/c\n",
    )
    fetcher = Fetcher(
        [
            (FetchStatus.ROBOTS_DISALLOWED, None),
            (FetchStatus.HTTP_ERROR, 403),
            (FetchStatus.FETCHED, 200),
        ]
    )
    extractor = Extractor()
    result = service(temp_settings, fetcher, extractor).collect(uuid4(), path)
    assert result.robots_blocked_count == 1
    assert result.http_access_failures == 1
    assert result.successful_fetches == extractor.calls == 1
    assert len(fetcher.urls) == 3


def test_hints_are_context_only_and_url_canonicalization() -> None:
    assert canonicalize_url("https://EXAMPLE.com:443/a#fragment") == "https://example.com/a"


def test_batch_cli_help_and_missing_job(
    runner, cli_with_settings, temp_settings, tmp_path: Path
) -> None:
    help_result = runner.invoke(cli_with_settings, ["batch", "collect", "--help"])
    assert help_result.exit_code == 0
    assert "--job-id" in help_result.stdout and "--file" in help_result.stdout
    engine = create_collector_engine(temp_settings.database_url)
    initialize_database(engine)
    engine.dispose()
    path = write_csv(tmp_path / "batch.csv", "source_url\nhttps://example.com/a\n")
    missing = runner.invoke(
        cli_with_settings,
        ["batch", "collect", "--job-id", str(uuid4()), "--file", str(path)],
    )
    assert missing.exit_code == 2
    assert "collection job does not exist" in missing.stderr
