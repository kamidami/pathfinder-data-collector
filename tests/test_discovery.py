import csv
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from pathfinder_collector.database import create_collector_engine, initialize_database
from pathfinder_collector.enums import EntityType, FetchStatus, RobotsStatus
from pathfinder_collector.fetching.exceptions import UnsafeUrlError
from pathfinder_collector.fetching.results import FetchResult
from pathfinder_collector.services.batch import BatchValidationError, read_batch_csv
from pathfinder_collector.services.discovery import (
    ProgrammeDiscoveryService,
    classify_programme_url,
    read_seed_csv,
)


def seed_file(path: Path, rows: str) -> Path:
    path.write_text(rows, encoding="utf-8")
    return path


class Jobs:
    def __init__(self, job=...) -> None:
        self.job = SimpleNamespace(entity_type=EntityType.PROGRAM) if job is ... else job

    def get(self, _job_id):
        return self.job


class Sources:
    def __init__(self, pages=None) -> None:
        self.pages = pages or []

    def list_for_job(self, _job_id):
        return self.pages


class Robots:
    def __init__(self, urls=None) -> None:
        self.urls = urls or []

    def sitemap_urls(self, _target):
        return self.urls


class Client:
    resolver = staticmethod(lambda _host: ["93.184.216.34"])

    def __init__(self, robots=None) -> None:
        self.robots = Robots(robots)


class UnresolvedClient(Client):
    @staticmethod
    def resolver(_host):
        raise UnsafeUrlError("hostname did not resolve")


class Fetcher:
    def __init__(
        self, tmp_path: Path, responses: dict[str, tuple[FetchStatus, str, str, int]]
    ) -> None:
        self.tmp_path = tmp_path
        self.responses = responses
        self.urls = []

    def fetch_url(self, _job_id, url, _source_type):
        self.urls.append(url)
        status, content_type, content, http_status = self.responses.get(
            url, (FetchStatus.HTTP_ERROR, "text/plain", "", 404)
        )
        cache_path = None
        if status is FetchStatus.FETCHED:
            cache_path = self.tmp_path / f"page-{len(self.urls)}"
            cache_path.write_bytes(content.encode())
        return FetchResult(
            source_page_id=uuid4(),
            requested_url=url,
            final_normalized_url=url,
            status=status,
            http_status=http_status,
            content_type=content_type,
            cache_path=cache_path,
            robots_status=(
                RobotsStatus.DISALLOWED
                if status is FetchStatus.ROBOTS_DISALLOWED
                else RobotsStatus.ALLOWED
            ),
        )


def make_service(temp_settings, tmp_path, responses, *, job=..., pages=None, robots=None):
    fetcher = Fetcher(tmp_path, responses)
    service = ProgrammeDiscoveryService(
        temp_settings, Jobs(job), Sources(pages), fetcher, Client(robots)
    )
    return service, fetcher


def test_valid_seed_csv_and_duplicates(tmp_path: Path) -> None:
    path = seed_file(
        tmp_path / "seeds.csv",
        "institution_name,official_domain,catalogue_url\n"
        "One,EXAMPLE.EDU,https://study.example.edu/programmes/\n"
        "Duplicate,example.edu,\n",
    )
    seeds, rows, duplicates = read_seed_csv(path)
    assert (len(seeds), rows, duplicates) == (1, 2, 1)
    assert seeds[0].catalogue_url == "https://study.example.edu/programmes"


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("official_domain\nexample.edu\n", "missing required seed headers"),
        ("institution_name,official_domain\nOne,https://example.edu/x\n", "row 2"),
        (
            "institution_name,official_domain,catalogue_url\nOne,example.edu,https://evil.edu/x\n",
            "must belong",
        ),
    ],
)
def test_seed_validation(content: str, message: str, tmp_path: Path) -> None:
    with pytest.raises(BatchValidationError, match=message):
        read_seed_csv(seed_file(tmp_path / "bad.csv", content))


def test_sitemap_discovery_and_batch_compatibility(temp_settings, tmp_path: Path) -> None:
    seeds = seed_file(
        tmp_path / "seeds.csv",
        "institution_name,official_domain,sitemap_url\n"
        "Example,example.edu,https://example.edu/custom.xml\n",
    )
    sitemap = (
        "<urlset><url><loc>https://example.edu/study/master/data-science/</loc></url>"
        "<url><loc>https://external.edu/program/master</loc></url></urlset>"
    )
    service, _ = make_service(
        temp_settings,
        tmp_path,
        {"https://example.edu/custom.xml": (FetchStatus.FETCHED, "application/xml", sitemap, 200)},
    )
    result = service.discover(uuid4(), seeds, 10)
    assert result.programme_url_candidates == 1
    output = result.output_directory / "discovered_programmes.csv"
    rows, count, duplicates = read_batch_csv(output)
    assert (len(rows), count, duplicates) == (1, 1, 0)
    assert rows[0].expected_university_name == "Example"


def test_sitemap_index_depth_limit(temp_settings, tmp_path: Path) -> None:
    temp_settings.discovery_max_sitemap_depth = 1
    seeds = seed_file(
        tmp_path / "seeds.csv",
        "institution_name,official_domain,sitemap_url\nExample,example.edu,https://example.edu/index.xml\n",
    )
    index = (
        "<sitemapindex><sitemap><loc>https://example.edu/child.xml</loc></sitemap></sitemapindex>"
    )
    child = (
        "<sitemapindex><sitemap><loc>https://example.edu/deep.xml</loc></sitemap></sitemapindex>"
    )
    service, fetcher = make_service(
        temp_settings,
        tmp_path,
        {
            "https://example.edu/index.xml": (FetchStatus.FETCHED, "application/xml", index, 200),
            "https://example.edu/child.xml": (FetchStatus.FETCHED, "application/xml", child, 200),
        },
    )
    service.discover(uuid4(), seeds, 10)
    assert "https://example.edu/deep.xml" not in fetcher.urls


def test_robots_sitemap_declaration(temp_settings, tmp_path: Path) -> None:
    seeds = seed_file(
        tmp_path / "seeds.csv", "institution_name,official_domain\nExample,example.edu\n"
    )
    sitemap = "<urlset><url><loc>https://example.edu/program/master-ai</loc></url></urlset>"
    service, fetcher = make_service(
        temp_settings,
        tmp_path,
        {"https://example.edu/robots-map.xml": (FetchStatus.FETCHED, "text/xml", sitemap, 200)},
        robots=["https://example.edu/robots-map.xml"],
    )
    result = service.discover(uuid4(), seeds, 2)
    assert result.programme_url_candidates == 1
    assert "https://example.edu/robots-map.xml" in fetcher.urls


def test_catalogue_links_same_origin_and_traps(temp_settings, tmp_path: Path) -> None:
    seeds = seed_file(
        tmp_path / "seeds.csv",
        "institution_name,official_domain,catalogue_url\n"
        "Example,example.edu,https://example.edu/catalogue\n",
    )
    page = (
        '<a href="/study/master-ai">Master of AI</a>'
        '<a href="https://evil.edu/program/master">Master external</a>'
        '<a href="/news/master-award">Master news</a>'
        '<a href="/files/degree.pdf">Degree PDF</a>'
    )
    service, _ = make_service(
        temp_settings,
        tmp_path,
        {"https://example.edu/catalogue": (FetchStatus.FETCHED, "text/html", page, 200)},
    )
    result = service.discover(uuid4(), seeds, 10)
    candidates = [item.canonical_url for item in result.items if item.result_status == "candidate"]
    assert candidates == ["https://example.edu/study/master-ai"]


def test_failures_continue_between_domains(temp_settings, tmp_path: Path) -> None:
    seeds = seed_file(
        tmp_path / "seeds.csv",
        "institution_name,official_domain,catalogue_url\n"
        "One,one.edu,https://one.edu/catalogue\n"
        "Two,two.edu,https://two.edu/catalogue\n"
        "Three,three.edu,https://three.edu/catalogue\n",
    )
    service, _ = make_service(
        temp_settings,
        tmp_path,
        {
            "https://one.edu/catalogue": (FetchStatus.ROBOTS_DISALLOWED, "", "", 0),
            "https://two.edu/catalogue": (FetchStatus.HTTP_ERROR, "", "", 403),
            "https://three.edu/catalogue": (
                FetchStatus.FETCHED,
                "text/html",
                '<a href="/program/master-ai">Master AI</a>',
                200,
            ),
        },
    )
    result = service.discover(uuid4(), seeds, 10)
    assert result.robots_blocked >= 1
    assert result.access_failures >= 1
    assert result.programme_url_candidates == 1


def test_http_403_existing_and_target_limit(temp_settings, tmp_path: Path) -> None:
    seeds = seed_file(
        tmp_path / "seeds.csv",
        "institution_name,official_domain,sitemap_url\nExample,example.edu,https://example.edu/map.xml\n",
    )
    sitemap = (
        "<urlset><url><loc>https://example.edu/program/master-one</loc></url>"
        "<url><loc>https://example.edu/program/master-two</loc></url></urlset>"
    )
    service, _ = make_service(
        temp_settings,
        tmp_path,
        {"https://example.edu/map.xml": (FetchStatus.FETCHED, "application/xml", sitemap, 200)},
        pages=[
            SimpleNamespace(
                original_url="https://example.edu/program/master-one",
                normalized_url="https://example.edu/program/master-one",
            )
        ],
    )
    result = service.discover(uuid4(), seeds, 1)
    assert result.already_existing_job_urls == 1
    assert result.programme_url_candidates == 1
    assert result.target_reached


def test_positive_and_negative_classification() -> None:
    score, signals = classify_programme_url("https://example.edu/study/master/data")
    assert score >= 20 and signals
    assert classify_programme_url("https://example.edu/news/master-award")[0] == 0
    assert classify_programme_url("https://example.edu/files/degree.pdf")[0] == 0


def test_missing_wrong_job_and_cli_help(
    runner, cli_with_settings, temp_settings, tmp_path: Path
) -> None:
    seeds = seed_file(
        tmp_path / "seeds.csv", "institution_name,official_domain\nExample,example.edu\n"
    )
    service, fetcher = make_service(temp_settings, tmp_path, {}, job=None)
    with pytest.raises(BatchValidationError, match="does not exist"):
        service.discover(uuid4(), seeds, 10)
    wrong, _ = make_service(
        temp_settings, tmp_path, {}, job=SimpleNamespace(entity_type=EntityType.SCHOLARSHIP)
    )
    with pytest.raises(BatchValidationError, match="must be program"):
        wrong.discover(uuid4(), seeds, 10)
    assert fetcher.urls == []
    help_result = runner.invoke(cli_with_settings, ["discover", "programs", "--help"])
    assert help_result.exit_code == 0 and "--seeds" in help_result.stdout
    engine = create_collector_engine(temp_settings.database_url)
    initialize_database(engine)
    engine.dispose()
    missing = runner.invoke(
        cli_with_settings,
        ["discover", "programs", "--job-id", str(uuid4()), "--seeds", str(seeds)],
    )
    assert missing.exit_code == 2
    assert "does not exist" in missing.stderr


def test_reports_are_safe_and_hints_only(temp_settings, tmp_path: Path) -> None:
    seeds = seed_file(
        tmp_path / "seeds.csv",
        "institution_name,official_domain,sitemap_url,operator_notes\n"
        "Example,example.edu,https://example.edu/map.xml,=operator hint\n",
    )
    sitemap = "<urlset><url><loc>https://example.edu/program/master-ai</loc></url></urlset>"
    service, _ = make_service(
        temp_settings,
        tmp_path,
        {"https://example.edu/map.xml": (FetchStatus.FETCHED, "application/xml", sitemap, 200)},
    )
    result = service.discover(uuid4(), seeds, 10)
    summary = (result.output_directory / "discovery_summary.json").read_text(encoding="utf-8")
    assert "<html" not in summary and "cache_path" not in summary and "Traceback" not in summary
    rows = list(
        csv.DictReader(
            (result.output_directory / "discovered_programmes.csv").open(
                encoding="utf-8", newline=""
            )
        )
    )
    assert rows[0]["operator_notes"] == "'=operator hint"
    assert rows[0]["expected_program_name"] == ""
    assert json.loads(summary)["target_reached"] is False


def test_controlled_failures_are_auditable_and_deduplicated(temp_settings, tmp_path: Path) -> None:
    seeds = seed_file(
        tmp_path / "seeds.csv",
        "institution_name,official_domain,catalogue_url,sitemap_url\n"
        "Unavailable,unresolved.example.invalid,https://unresolved.example.invalid/catalogue,"
        "https://unresolved.example.invalid/sitemap.xml\n",
    )
    failed = (FetchStatus.NETWORK_ERROR, "text/plain", "", 0)
    fetcher = Fetcher(
        tmp_path,
        {
            "https://unresolved.example.invalid/sitemap.xml": failed,
            "https://unresolved.example.invalid/sitemap_index.xml": failed,
            "https://unresolved.example.invalid/catalogue": failed,
        },
    )
    service = ProgrammeDiscoveryService(
        temp_settings, Jobs(), Sources(), fetcher, UnresolvedClient()
    )
    result = service.discover(uuid4(), seeds, 10)
    failure_items = [item for item in result.items if item.result_status != "candidate"]
    assert result.controlled_failures == len(failure_items) == 4
    assert {item.result_status for item in failure_items} == {
        "robots_failed",
        "sitemap_failed",
        "catalogue_failed",
    }
    keys = {
        (item.official_domain, item.canonical_url, item.discovery_source, item.result_status)
        for item in failure_items
    }
    assert len(keys) == len(failure_items)
    summary_path = result.output_directory / "discovery_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert len(summary["results"]) == 4
    with (result.output_directory / "discovery_results.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        reported = list(csv.DictReader(handle))
    assert len(reported) == 4
    serialized = json.dumps(summary)
    assert "Traceback" not in serialized and "cache_path" not in serialized
    assert "hostname did not resolve" not in serialized
