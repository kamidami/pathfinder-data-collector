import csv
import gzip
import io
import json
import re
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from uuid import UUID, uuid4

from lxml import etree, html
from pydantic import BaseModel, Field

from pathfinder_collector import __version__
from pathfinder_collector.config import Settings
from pathfinder_collector.enums import EntityType, FetchStatus, SourceType
from pathfinder_collector.fetching.client import SafeHttpClient
from pathfinder_collector.fetching.exceptions import FetchingError
from pathfinder_collector.fetching.urls import validate_url
from pathfinder_collector.persistence.repositories import JobRepository, SourcePageRepository
from pathfinder_collector.services.batch import BatchValidationError, canonicalize_url
from pathfinder_collector.services.fetching import FetchService

SEED_COLUMNS = {
    "institution_name",
    "official_domain",
    "catalogue_url",
    "sitemap_url",
    "operator_notes",
}
POSITIVE_TERMS = {
    "programme",
    "program",
    "programmes",
    "programs",
    "degree",
    "degrees",
    "study",
    "bachelor",
    "master",
    "msc",
    "bsc",
    "course-of-study",
    "studiengang",
    "studium",
}
TRAP_TERMS = {
    "login",
    "account",
    "calendar",
    "news",
    "event",
    "events",
    "privacy",
    "legal",
    "staff",
    "people",
    "publication",
    "publications",
    "contact",
    "search",
}
MEDIA_SUFFIXES = (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".zip", ".doc", ".docx")


class DiscoverySeed(BaseModel):
    row_number: int
    institution_name: str
    official_domain: str
    catalogue_url: str = ""
    sitemap_url: str = ""
    operator_notes: str = ""


class DiscoveryItem(BaseModel):
    institution_name: str
    official_domain: str
    discovered_url: str
    canonical_url: str
    discovery_source: str
    discovery_score: int
    matched_signals: list[str] = Field(default_factory=list)
    result_status: str
    message: str = ""


class DiscoveryResult(BaseModel):
    discovery_run_id: UUID = Field(default_factory=uuid4)
    job_id: UUID
    target_requested: int
    seed_rows: int
    valid_unique_domains: int
    duplicate_domains: int
    domains_processed: int = 0
    sitemap_urls_checked: int = 0
    catalogue_pages_checked: int = 0
    pages_fetched: int = 0
    cache_hits: int = 0
    raw_links_found: int = 0
    programme_url_candidates: int = 0
    duplicate_urls: int = 0
    already_existing_job_urls: int = 0
    robots_blocked: int = 0
    access_failures: int = 0
    controlled_failures: int = 0
    target_reached: bool = False
    items: list[DiscoveryItem] = Field(default_factory=list)
    output_directory: Path | None = None


def read_seed_csv(path: Path) -> tuple[list[DiscoverySeed], int, int]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise BatchValidationError(["seed CSV must be UTF-8"]) from exc
    except OSError as exc:
        raise BatchValidationError([f"cannot read seed CSV: {exc}"]) from exc
    reader = csv.DictReader(io.StringIO(text, newline=""))
    required = {"institution_name", "official_domain"}
    if reader.fieldnames is None or not required.issubset(reader.fieldnames):
        missing = sorted(required - set(reader.fieldnames or []))
        raise BatchValidationError([f"missing required seed headers: {', '.join(missing)}"])
    extra = sorted(set(reader.fieldnames) - SEED_COLUMNS)
    if extra:
        raise BatchValidationError([f"unknown seed columns: {', '.join(extra)}"])
    errors: list[str] = []
    seeds: list[DiscoverySeed] = []
    seen: set[str] = set()
    duplicates = 0
    row_count = 0
    for row_number, raw in enumerate(reader, start=2):
        values = {key: (raw.get(key) or "").strip() for key in SEED_COLUMNS}
        if not any(values.values()):
            continue
        row_count += 1
        domain = values["official_domain"].lower().rstrip(".")
        if not values["institution_name"]:
            errors.append(f"row {row_number}: institution_name is required")
        if not _valid_domain(domain):
            errors.append(f"row {row_number}: official_domain must be a hostname only")
            continue
        invalid_url = False
        for field in ("catalogue_url", "sitemap_url"):
            if not values[field]:
                continue
            try:
                values[field] = canonicalize_url(values[field])
            except ValueError as exc:
                errors.append(f"row {row_number}: {field} {exc}")
                invalid_url = True
                continue
            if not _within_domain(urlsplit(values[field]).hostname or "", domain):
                errors.append(f"row {row_number}: {field} must belong to official_domain")
                invalid_url = True
        if invalid_url:
            continue
        if domain in seen:
            duplicates += 1
            continue
        seen.add(domain)
        values["official_domain"] = domain
        seeds.append(DiscoverySeed(row_number=row_number, **values))
    if errors:
        raise BatchValidationError(errors)
    return seeds, row_count, duplicates


def classify_programme_url(
    url: str, text: str = "", *, catalogue: bool = False
) -> tuple[int, list[str]]:
    path = urlsplit(url).path.casefold()
    combined = f"{path} {text.casefold()}"
    if path.endswith(MEDIA_SUFFIXES) or any(
        re.search(rf"(?:^|[\W_/.-]){re.escape(term)}(?:$|[\W_/.-])", combined)
        for term in TRAP_TERMS
    ):
        return 0, ["negative:trap-or-media"]
    signals: list[str] = []
    path_hits = sorted(term for term in POSITIVE_TERMS if term in path)
    text_hits = sorted(term for term in POSITIVE_TERMS if term in text.casefold())
    if path_hits:
        signals.append("path:" + ",".join(path_hits[:4]))
    if text_hits:
        signals.append("text:" + ",".join(text_hits[:4]))
    if catalogue:
        signals.append("catalogue-context")
    score = min(100, len(path_hits) * 25 + len(text_hits) * 15 + (20 if catalogue else 0))
    return score, signals


class ProgrammeDiscoveryService:
    def __init__(
        self,
        settings: Settings,
        jobs: JobRepository,
        sources: SourcePageRepository,
        fetcher: FetchService,
        client: SafeHttpClient,
    ) -> None:
        self.settings = settings
        self.jobs = jobs
        self.sources = sources
        self.fetcher = fetcher
        self.client = client

    def discover(self, job_id: UUID, seeds_path: Path, target: int) -> DiscoveryResult:
        job = self.jobs.get(job_id)
        if job is None:
            raise BatchValidationError(["collection job does not exist"])
        if job.entity_type is not EntityType.PROGRAM:
            raise BatchValidationError(["collection job entity type must be program"])
        if not 1 <= target <= 10000:
            raise BatchValidationError(["target must be between 1 and 10000"])
        seeds, rows, duplicate_domains = read_seed_csv(seeds_path)
        result = DiscoveryResult(
            job_id=job_id,
            target_requested=target,
            seed_rows=rows,
            valid_unique_domains=len(seeds),
            duplicate_domains=duplicate_domains,
        )
        known = self._known_job_urls(job_id)
        emitted: set[str] = set()
        for seed in seeds:
            if len(emitted) >= target:
                break
            result.domains_processed += 1
            self._discover_seed(job_id, seed, result, emitted, known, target)
        result.programme_url_candidates = len(emitted)
        result.target_reached = len(emitted) >= target
        result.output_directory = self._write_reports(result, seeds)
        return result

    def _discover_seed(
        self,
        job_id: UUID,
        seed: DiscoverySeed,
        result: DiscoveryResult,
        emitted: set[str],
        known: set[str],
        target: int,
    ) -> None:
        base = f"https://{seed.official_domain}/"
        sitemap_queue: deque[tuple[str, int, str]] = deque()
        if seed.sitemap_url:
            sitemap_queue.append((seed.sitemap_url, 0, "explicit_sitemap"))
        try:
            safe_root = validate_url(base, self.client.resolver)
            for url in self.client.robots.sitemap_urls(safe_root):
                if _url_allowed(url, seed.official_domain):
                    sitemap_queue.append((canonicalize_url(url), 0, "robots_sitemap"))
        except (OSError, ValueError, FetchingError):
            self._record_failure(
                seed,
                urljoin(base, "robots.txt"),
                "robots_txt",
                "robots_failed",
                "robots.txt could not be evaluated safely.",
                result,
            )
        sitemap_queue.extend(
            [
                (urljoin(base, "sitemap.xml"), 0, "conventional_sitemap"),
                (urljoin(base, "sitemap_index.xml"), 0, "conventional_sitemap"),
            ]
        )
        checked: set[str] = set()
        while sitemap_queue and len(checked) < self.settings.discovery_max_sitemaps:
            if len(emitted) >= target:
                return
            url, depth, source = sitemap_queue.popleft()
            canonical = canonicalize_url(url)
            if canonical in checked or not _url_allowed(canonical, seed.official_domain):
                continue
            checked.add(canonical)
            result.sitemap_urls_checked += 1
            fetched = self._fetch(job_id, canonical, seed, source, "sitemap_failed", result)
            if fetched is None:
                continue
            parsed_urls, is_index, valid = _parse_sitemap(fetched, self.settings.max_response_bytes)
            if not valid:
                self._record_failure(
                    seed,
                    canonical,
                    source,
                    "sitemap_failed",
                    "Sitemap content could not be parsed safely.",
                    result,
                )
                continue
            for location in parsed_urls[: self.settings.discovery_max_links]:
                result.raw_links_found += 1
                if not _url_allowed(location, seed.official_domain):
                    continue
                canonical_location = canonicalize_url(location)
                if is_index:
                    if depth < self.settings.discovery_max_sitemap_depth:
                        sitemap_queue.append((canonical_location, depth + 1, "sitemap_index"))
                    continue
                self._consider(seed, canonical_location, source, "", result, emitted, known, target)
                if len(emitted) >= target:
                    return

        starts = [seed.catalogue_url] if seed.catalogue_url else [base]
        queue: deque[tuple[str, int, bool]] = deque(
            (url, 0, bool(seed.catalogue_url)) for url in starts
        )
        crawled: set[str] = set()
        while queue and len(crawled) < self.settings.discovery_max_pages_per_domain:
            if len(emitted) >= target:
                return
            url, depth, catalogue = queue.popleft()
            canonical = canonicalize_url(url)
            if canonical in crawled or not _url_allowed(canonical, seed.official_domain):
                continue
            crawled.add(canonical)
            result.catalogue_pages_checked += int(catalogue)
            failure_status = (
                "catalogue_failed"
                if catalogue
                else "crawl_seed_failed"
                if depth == 0
                else "controlled_failure"
            )
            fetched = self._fetch(
                job_id,
                canonical,
                seed,
                "catalogue" if catalogue else "crawl",
                failure_status,
                result,
            )
            if fetched is None or fetched.content_type not in {
                "text/html",
                "application/xhtml+xml",
            }:
                continue
            links = _html_links(fetched)
            for href, text in links[: self.settings.discovery_max_links]:
                result.raw_links_found += 1
                absolute = urljoin(canonical, href)
                if not _url_allowed(absolute, seed.official_domain):
                    continue
                candidate = canonicalize_url(absolute)
                self._consider(
                    seed,
                    candidate,
                    "catalogue" if catalogue else "crawl",
                    text,
                    result,
                    emitted,
                    known,
                    target,
                    catalogue=catalogue,
                )
                if depth < self.settings.discovery_max_crawl_depth and not _is_trap(candidate):
                    queue.append((candidate, depth + 1, catalogue))
                if len(emitted) >= target:
                    return

    def _fetch(
        self,
        job_id: UUID,
        url: str,
        seed: DiscoverySeed,
        source: str,
        failure_status: str,
        result: DiscoveryResult,
    ):
        fetched = self.fetcher.fetch_url(job_id, url, SourceType.DISCOVERY)
        result.cache_hits += int(fetched.cache_hit)
        if fetched.status not in {FetchStatus.FETCHED, FetchStatus.CACHE_HIT}:
            result.robots_blocked += int(fetched.status is FetchStatus.ROBOTS_DISALLOWED)
            result.access_failures += int(
                fetched.status is FetchStatus.HTTP_ERROR and fetched.http_status in {401, 403, 404}
            )
            status = (
                "access_blocked"
                if fetched.status is FetchStatus.ROBOTS_DISALLOWED
                or (
                    fetched.status is FetchStatus.HTTP_ERROR
                    and fetched.http_status in {401, 403, 404}
                )
                else "robots_failed"
                if fetched.status is FetchStatus.ROBOTS_UNAVAILABLE
                else failure_status
            )
            message = (
                f"HTTP access blocked ({fetched.http_status})."
                if fetched.http_status in {401, 403, 404}
                else "robots.txt disallows this URL."
                if fetched.status is FetchStatus.ROBOTS_DISALLOWED
                else f"Controlled fetch failure: {fetched.status.value}."
            )
            self._record_failure(seed, url, source, status, message, result)
            return None
        result.pages_fetched += 1
        return fetched

    @staticmethod
    def _record_failure(
        seed: DiscoverySeed,
        url: str,
        source: str,
        status: str,
        message: str,
        result: DiscoveryResult,
    ) -> None:
        canonical = _safe_canonical(url)
        key = (seed.official_domain, canonical, source, status)
        existing = {
            (item.official_domain, item.canonical_url, item.discovery_source, item.result_status)
            for item in result.items
            if item.result_status not in {"candidate", "duplicate", "already_existing"}
        }
        if key in existing:
            return
        result.items.append(
            DiscoveryItem(
                institution_name=seed.institution_name,
                official_domain=seed.official_domain,
                discovered_url=_without_query(url),
                canonical_url=canonical,
                discovery_source=source,
                discovery_score=0,
                matched_signals=[],
                result_status=status,
                message=message[:300],
            )
        )
        result.controlled_failures += 1

    def _consider(
        self,
        seed: DiscoverySeed,
        url: str,
        source: str,
        text: str,
        result: DiscoveryResult,
        emitted: set[str],
        known: set[str],
        target: int,
        *,
        catalogue: bool = False,
    ) -> None:
        if len(emitted) >= target:
            return
        score, signals = classify_programme_url(url, text, catalogue=catalogue)
        if score < 20:
            return
        status = "candidate"
        message = "Requires programme extraction and human review."
        if url in emitted:
            result.duplicate_urls += 1
            status, message = "duplicate", "Equivalent URL already found in this run."
        elif url in known:
            result.already_existing_job_urls += 1
            status, message = "already_existing", "URL is already associated with this job."
        else:
            emitted.add(url)
        result.items.append(
            DiscoveryItem(
                institution_name=seed.institution_name,
                official_domain=seed.official_domain,
                discovered_url=_without_query(url),
                canonical_url=_without_query(url),
                discovery_source=source,
                discovery_score=score,
                matched_signals=signals,
                result_status=status,
                message=message,
            )
        )

    def _known_job_urls(self, job_id: UUID) -> set[str]:
        known: set[str] = set()
        for page in self.sources.list_for_job(job_id):
            for value in (str(page.original_url), str(page.normalized_url)):
                try:
                    known.add(canonicalize_url(value))
                except ValueError:
                    continue
        return known

    def _write_reports(self, result: DiscoveryResult, seeds: list[DiscoverySeed]) -> Path:
        directory = self.settings.report_dir / "discovery" / str(result.discovery_run_id)
        directory.mkdir(parents=True, exist_ok=False)
        aggregate = result.model_dump(exclude={"items", "output_directory"}, mode="json")
        payload = {
            "collector_version": __version__,
            "generated_at": datetime.now(UTC).isoformat(),
            **aggregate,
            "results": [item.model_dump(mode="json") for item in result.items],
        }
        (directory / "discovery_summary.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        _write_csv(
            directory / "discovery_results.csv",
            list(DiscoveryItem.model_fields),
            [item.model_dump(mode="json") for item in result.items],
        )
        seed_by_domain = {seed.official_domain: seed for seed in seeds}
        programme_rows = []
        for item in result.items:
            if item.result_status != "candidate":
                continue
            seed = seed_by_domain[item.official_domain]
            programme_rows.append(
                {
                    "source_url": item.canonical_url,
                    "expected_university_name": item.institution_name,
                    "expected_program_name": "",
                    "operator_notes": seed.operator_notes,
                }
            )
        _write_csv(
            directory / "discovered_programmes.csv",
            [
                "source_url",
                "expected_university_name",
                "expected_program_name",
                "operator_notes",
            ],
            programme_rows,
        )
        shortfall = max(0, result.target_requested - result.programme_url_candidates)
        lines = [
            f"Discovery run: {result.discovery_run_id}",
            f"Job: {result.job_id}",
            f"Candidates: {result.programme_url_candidates}/{result.target_requested}",
            f"Target reached: {'yes' if result.target_reached else 'no'}",
            f"Shortfall: {shortfall}",
            "Discovery is not verification; extraction and human review remain mandatory.",
        ]
        (directory / "discovery_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return directory


def _parse_sitemap(result: object, maximum: int) -> tuple[list[str], bool, bool]:
    if not result.cache_path:
        return [], False, False
    try:
        content = result.cache_path.read_bytes()
        if result.content_type in {"application/gzip", "application/x-gzip"} or str(
            result.final_normalized_url
        ).endswith(".gz"):
            with gzip.GzipFile(fileobj=io.BytesIO(content)) as compressed:
                content = compressed.read(maximum + 1)
        if len(content) > maximum:
            return [], False, False
        root = etree.fromstring(
            content,
            parser=etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False),
        )
    except (OSError, EOFError, gzip.BadGzipFile, etree.XMLSyntaxError):
        return [], False, False
    locations = [str(value).strip() for value in root.xpath("//*[local-name()='loc']/text()")]
    root_type = root.tag.rsplit("}", 1)[-1].casefold()
    if root_type not in {"urlset", "sitemapindex"}:
        return [], False, False
    return locations, root_type == "sitemapindex", True


def _html_links(result: object) -> list[tuple[str, str]]:
    if not result.cache_path:
        return []
    try:
        document = html.fromstring(result.cache_path.read_bytes())
    except (OSError, etree.ParserError):
        return []
    links: list[tuple[str, str]] = []
    for anchor in document.xpath("//a[@href]"):
        links.append((anchor.get("href", ""), " ".join(anchor.text_content().split())[:300]))
    return links


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\r\n")
        writer.writeheader()
        for row in rows:
            values = dict(row)
            if isinstance(values.get("matched_signals"), list):
                values["matched_signals"] = ";".join(values["matched_signals"])
            writer.writerow({key: _formula_safe(value) for key, value in values.items()})


def _valid_domain(value: str) -> bool:
    return bool(
        len(value) <= 253
        and "." in value
        and re.fullmatch(
            r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", value
        )
    )


def _within_domain(host: str, domain: str) -> bool:
    normalized = host.casefold().rstrip(".")
    return normalized == domain or normalized.endswith("." + domain)


def _url_allowed(url: str, domain: str) -> bool:
    try:
        canonical = canonicalize_url(url)
    except ValueError:
        return False
    return _within_domain(urlsplit(canonical).hostname or "", domain) and not _is_trap(canonical)


def _is_trap(url: str) -> bool:
    path = urlsplit(url).path.casefold()
    return path.endswith(MEDIA_SUFFIXES) or any(term in path.split("/") for term in TRAP_TERMS)


def _without_query(url: str) -> str:
    return url.split("?", 1)[0]


def _safe_canonical(url: str) -> str:
    try:
        return _without_query(canonicalize_url(url))
    except ValueError:
        return _without_query(url)[:4096]


def _formula_safe(value: object) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(("=", "+", "-", "@", "\t", "\r")) else text
