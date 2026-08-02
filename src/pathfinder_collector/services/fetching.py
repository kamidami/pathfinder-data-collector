from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from pathfinder_collector.config import Settings
from pathfinder_collector.domain.evidence import SourcePage
from pathfinder_collector.enums import FetchStatus, SourceType
from pathfinder_collector.fetching.client import SafeHttpClient
from pathfinder_collector.fetching.hashing import sha256_bytes
from pathfinder_collector.fetching.results import FetchResult
from pathfinder_collector.fetching.urls import validate_url
from pathfinder_collector.persistence.repositories import JobRepository, SourcePageRepository


class FetchService:
    def __init__(
        self,
        settings: Settings,
        jobs: JobRepository,
        sources: SourcePageRepository,
        client: SafeHttpClient,
    ) -> None:
        self.settings = settings
        self.jobs = jobs
        self.sources = sources
        self.client = client

    def fetch_url(
        self,
        job_id: UUID,
        url: str,
        source_type: SourceType,
        *,
        force_refresh: bool = False,
    ) -> FetchResult:
        if not self.jobs.exists(job_id):
            raise ValueError("collection job does not exist")
        try:
            initial = validate_url(url, self.client.resolver)
        except Exception:
            return self.client.fetch(url)
        existing = self.sources.find(job_id, initial.normalized_url)
        if existing and not force_refresh:
            hit = self._cache_hit(existing)
            if hit:
                return hit
        result = self.client.fetch(initial.normalized_url)
        page = self._to_page(job_id, initial.normalized_url, source_type, result, existing)
        result.source_page_id = page.id
        self.sources.save(page)
        return result

    def list_sources(self, job_id: UUID) -> list[SourcePage]:
        if not self.jobs.exists(job_id):
            raise ValueError("collection job does not exist")
        return self.sources.list_for_job(job_id)

    def _cache_hit(self, page: SourcePage) -> FetchResult | None:
        if (
            page.fetch_status not in {FetchStatus.FETCHED, FetchStatus.CACHE_HIT}
            or page.cache_expires_at is None
            or page.cache_expires_at <= datetime.now(UTC)
            or not page.cached_file_path
            or not page.content_hash
        ):
            return None
        path = Path(page.cached_file_path)
        try:
            content = path.read_bytes()
        except OSError:
            return None
        if sha256_bytes(content) != page.content_hash:
            return None
        page.fetch_status = FetchStatus.CACHE_HIT
        self.sources.save(page)
        return FetchResult(
            source_page_id=page.id,
            requested_url=str(page.original_url),
            final_normalized_url=str(page.normalized_url),
            safe_display_url=_without_query(str(page.normalized_url)),
            status=FetchStatus.CACHE_HIT,
            http_status=page.http_status,
            content_type=page.content_type,
            response_bytes=page.response_bytes,
            content_hash=page.content_hash,
            cache_path=path,
            fetched_at=page.fetched_at,
            cache_hit=True,
            robots_status=page.robots_status,
            redirect_count=page.redirect_count,
        )

    def _to_page(
        self,
        job_id: UUID,
        original_url: str,
        source_type: SourceType,
        result: FetchResult,
        existing: SourcePage | None,
    ) -> SourcePage:
        final_url = result.final_normalized_url or original_url
        expires_at = (
            result.fetched_at + timedelta(hours=self.settings.cache_ttl_hours)
            if result.fetched_at and result.content_hash
            else None
        )
        values = {
            "job_id": job_id,
            "original_url": original_url,
            "normalized_url": final_url,
            "source_type": source_type,
            "official_domain": source_type is not SourceType.DISCOVERY,
            "fetch_status": result.status,
            "content_hash": result.content_hash,
            "cached_file_path": str(result.cache_path) if result.cache_path else None,
            "fetched_at": result.fetched_at,
            "robots_status": result.robots_status,
            "http_status": result.http_status,
            "content_type": result.content_type,
            "response_bytes": result.response_bytes,
            "redirect_count": result.redirect_count,
            "cache_expires_at": expires_at,
            "error_code": result.safe_error_code,
            "safe_error_summary": result.safe_error_summary,
        }
        if existing:
            for name, value in values.items():
                setattr(existing, name, value)
            return existing
        return SourcePage(**values)


def _without_query(url: str) -> str:
    return url.split("?", 1)[0]
