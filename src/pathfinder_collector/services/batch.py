import csv
import io
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import SplitResult, urlsplit, urlunsplit
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from pathfinder_collector import __version__
from pathfinder_collector.config import Settings
from pathfinder_collector.enums import (
    CandidateStatus,
    EntityType,
    ExtractionStatus,
    FetchStatus,
    SourceType,
)
from pathfinder_collector.persistence.repositories import (
    CandidateRepository,
    JobRepository,
    SourcePageRepository,
)
from pathfinder_collector.services.extraction import ProgrammeExtractionService
from pathfinder_collector.services.fetching import FetchService

INPUT_COLUMNS = {
    "source_url",
    "expected_university_name",
    "expected_program_name",
    "operator_notes",
}


class BatchValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


class BatchInputRow(BaseModel):
    row_number: int
    source_url: str
    canonical_url: str
    expected_university_name: str = ""
    expected_program_name: str = ""
    operator_notes: str = ""


class BatchRowResult(BaseModel):
    row_number: int
    source_url: str
    canonical_url: str
    result_status: str
    fetch_status: str = ""
    http_status: int | None = None
    cache_used: bool = False
    source_id: UUID | None = None
    candidate_id: UUID | None = None
    review_status: str = ""
    message: str = ""
    expected_university_name: str = ""
    expected_program_name: str = ""
    operator_notes: str = ""
    operator_context: dict[str, str] = Field(default_factory=dict)


class BatchResult(BaseModel):
    batch_run_id: UUID = Field(default_factory=uuid4)
    job_id: UUID
    input_row_count: int
    valid_unique_urls: int
    duplicate_input_urls: int
    already_existing_urls: int = 0
    successful_fetches: int = 0
    cache_hits: int = 0
    extraction_successes: int = 0
    candidates_created: int = 0
    candidates_reused: int = 0
    needs_review_count: int = 0
    robots_blocked_count: int = 0
    http_access_failures: int = 0
    validation_failures: int = 0
    controlled_failures: int = 0
    results: list[BatchRowResult] = Field(default_factory=list)
    report_directory: Path | None = None


def read_batch_csv(path: Path) -> tuple[list[BatchInputRow], int, int]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise BatchValidationError(["input CSV must be UTF-8"]) from exc
    except OSError as exc:
        raise BatchValidationError([f"cannot read input CSV: {exc}"]) from exc
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if reader.fieldnames is None or "source_url" not in reader.fieldnames:
        raise BatchValidationError(["missing required source_url header"])
    extras = sorted(set(reader.fieldnames) - INPUT_COLUMNS)
    if extras:
        raise BatchValidationError([f"unknown input columns: {', '.join(extras)}"])
    errors: list[str] = []
    rows: list[BatchInputRow] = []
    seen: set[str] = set()
    duplicates = 0
    input_count = 0
    for row_number, raw in enumerate(reader, start=2):
        values = {key: (raw.get(key) or "").strip() for key in INPUT_COLUMNS}
        if not any(values.values()):
            continue
        input_count += 1
        try:
            canonical = canonicalize_url(values["source_url"])
        except ValueError as exc:
            errors.append(f"row {row_number}: {exc}")
            continue
        if canonical in seen:
            duplicates += 1
            continue
        seen.add(canonical)
        rows.append(
            BatchInputRow(
                row_number=row_number,
                canonical_url=canonical,
                **values,
            )
        )
    if errors:
        raise BatchValidationError(errors)
    return rows, input_count, duplicates


def canonicalize_url(value: str) -> str:
    if not value:
        raise ValueError("source_url is required")
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError as exc:
        raise ValueError("source_url is malformed") from exc
    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"}:
        raise ValueError("source_url must use HTTP or HTTPS")
    if not parts.hostname:
        raise ValueError("source_url must be absolute and contain a hostname")
    if parts.username is not None or parts.password is not None:
        raise ValueError("source_url must not contain credentials")
    host = parts.hostname.rstrip(".").lower()
    default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    netloc = host if port is None or default_port else f"{host}:{port}"
    return urlunsplit(SplitResult(scheme, netloc, parts.path or "/", parts.query, ""))


class BatchCollectionService:
    def __init__(
        self,
        settings: Settings,
        jobs: JobRepository,
        sources: SourcePageRepository,
        candidates: CandidateRepository,
        fetcher: FetchService,
        extractor: ProgrammeExtractionService,
    ) -> None:
        self.settings = settings
        self.jobs = jobs
        self.sources = sources
        self.candidates = candidates
        self.fetcher = fetcher
        self.extractor = extractor

    def collect(self, job_id: UUID, path: Path) -> BatchResult:
        job = self.jobs.get(job_id)
        if job is None:
            raise BatchValidationError(["collection job does not exist"])
        if job.entity_type is not EntityType.PROGRAM:
            raise BatchValidationError(["collection job entity type must be program"])
        rows, input_count, duplicates = read_batch_csv(path)
        result = BatchResult(
            job_id=job_id,
            input_row_count=input_count,
            valid_unique_urls=len(rows),
            duplicate_input_urls=duplicates,
        )
        existing: dict[str, object] = {}
        for page in self.sources.list_for_job(job_id):
            for stored_url in (str(page.original_url), str(page.normalized_url)):
                try:
                    existing[canonicalize_url(stored_url)] = page
                except ValueError:
                    continue
        for row in rows:
            context = {
                key: value
                for key, value in {
                    "expected_university_name": row.expected_university_name,
                    "expected_program_name": row.expected_program_name,
                    "operator_notes": row.operator_notes,
                }.items()
                if value
            }
            page = existing.get(row.canonical_url)
            if page:
                candidate = self.candidates.find_by_source(job_id, page.id)
                result.already_existing_urls += 1
                if candidate:
                    result.candidates_reused += 1
                    result.needs_review_count += int(
                        candidate.review_status is CandidateStatus.NEEDS_REVIEW
                    )
                result.results.append(
                    BatchRowResult(
                        row_number=row.row_number,
                        source_url=_without_query(row.source_url),
                        canonical_url=_without_query(row.canonical_url),
                        result_status="already_existing",
                        fetch_status=page.fetch_status.value,
                        http_status=page.http_status,
                        source_id=page.id,
                        candidate_id=candidate.id if candidate else None,
                        review_status=candidate.review_status.value if candidate else "",
                        message="URL already belongs to this job; no records changed.",
                        expected_university_name=row.expected_university_name,
                        expected_program_name=row.expected_program_name,
                        operator_notes=row.operator_notes,
                        operator_context=context,
                    )
                )
                continue
            fetched = self.fetcher.fetch_url(job_id, row.canonical_url, SourceType.OFFICIAL_PROGRAM)
            item = BatchRowResult(
                row_number=row.row_number,
                source_url=_without_query(row.source_url),
                canonical_url=_without_query(row.canonical_url),
                result_status="fetch_failed",
                fetch_status=fetched.status.value,
                http_status=fetched.http_status,
                cache_used=fetched.cache_hit,
                source_id=fetched.source_page_id,
                message=fetched.safe_error_summary
                or fetched.safe_error_code
                or "Fetch did not succeed.",
                expected_university_name=row.expected_university_name,
                expected_program_name=row.expected_program_name,
                operator_notes=row.operator_notes,
                operator_context=context,
            )
            result.cache_hits += int(fetched.cache_hit)
            if fetched.status not in {FetchStatus.FETCHED, FetchStatus.CACHE_HIT}:
                result.robots_blocked_count += int(fetched.status is FetchStatus.ROBOTS_DISALLOWED)
                result.http_access_failures += int(
                    fetched.status is FetchStatus.HTTP_ERROR
                    and fetched.http_status in {401, 403, 404}
                )
                result.controlled_failures += 1
                result.results.append(item)
                continue
            result.successful_fetches += 1
            extracted = self.extractor.extract_source(job_id, fetched.source_page_id)
            item.candidate_id = extracted.candidate_id
            item.review_status = (
                extracted.candidate_status.value if extracted.candidate_status else ""
            )
            item.result_status = extracted.extraction_status.value
            item.message = "; ".join(extracted.warnings[:3])
            if extracted.extraction_status in {
                ExtractionStatus.EXTRACTED,
                ExtractionStatus.PARTIAL,
            }:
                result.extraction_successes += 1
                result.candidates_created += int(extracted.created_candidate)
                result.candidates_reused += int(extracted.updated_candidate)
                result.needs_review_count += int(
                    extracted.candidate_status is CandidateStatus.NEEDS_REVIEW
                )
            else:
                result.controlled_failures += 1
            result.results.append(item)
        result.report_directory = self._write_reports(result)
        return result

    def _write_reports(self, result: BatchResult) -> Path:
        directory = self.settings.report_dir / "batches" / str(result.batch_run_id)
        directory.mkdir(parents=True, exist_ok=False)
        generated_at = datetime.now(UTC)
        aggregate = result.model_dump(exclude={"results", "report_directory"}, mode="json")
        payload = {
            "collector_version": __version__,
            "generated_at": generated_at.isoformat(),
            **aggregate,
            "results": [item.model_dump(mode="json") for item in result.results],
        }
        (directory / "batch_summary.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        fields = list(BatchRowResult.model_fields)
        with (directory / "batch_results.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\r\n")
            writer.writeheader()
            for item in result.results:
                row = item.model_dump(mode="json")
                row["operator_context"] = json.dumps(row["operator_context"], sort_keys=True)
                writer.writerow({key: _formula_safe(value) for key, value in row.items()})
        lines = [
            f"Batch run: {result.batch_run_id}",
            f"Job: {result.job_id}",
            f"Input rows: {result.input_row_count}",
            f"Valid unique URLs: {result.valid_unique_urls}",
            f"Duplicate input URLs: {result.duplicate_input_urls}",
            f"Already existing URLs: {result.already_existing_urls}",
            f"Successful fetches: {result.successful_fetches}",
            f"Extraction successes: {result.extraction_successes}",
            "Human review remains mandatory.",
        ]
        (directory / "batch_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return directory


def _formula_safe(value: object) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(("=", "+", "-", "@", "\t", "\r")) else text


def _without_query(value: str) -> str:
    parts = urlsplit(value)
    return urlunsplit(SplitResult(parts.scheme, parts.netloc, parts.path, "", ""))
