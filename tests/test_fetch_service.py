from collections import Counter

import httpx
from sqlalchemy import func, select

from pathfinder_collector.config import Settings
from pathfinder_collector.database import (
    create_collector_engine,
    initialize_database,
    session_scope,
)
from pathfinder_collector.domain.candidates import CandidateRecord
from pathfinder_collector.domain.jobs import CollectionJob
from pathfinder_collector.enums import CandidateStatus, EntityType, FetchStatus, SourceType
from pathfinder_collector.fetching.client import SafeHttpClient
from pathfinder_collector.persistence.models import CandidateModel, SourcePageModel
from pathfinder_collector.persistence.repositories import JobRepository, SourcePageRepository
from pathfinder_collector.services.fetching import FetchService


def public_resolver(host: str) -> list[str]:
    return ["93.184.216.34"]


def test_cache_hit_force_refresh_corruption_and_persistence(temp_settings: Settings) -> None:
    calls = Counter()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            calls["robots"] += 1
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        calls["page"] += 1
        return httpx.Response(
            200, headers={"content-type": "text/html"}, content=f"page-{calls['page']}"
        )

    engine = create_collector_engine(temp_settings.database_url)
    initialize_database(engine)
    fetcher = SafeHttpClient(
        temp_settings,
        transport=httpx.MockTransport(handler),
        resolver=public_resolver,
        sleep=lambda seconds: None,
    )
    with session_scope(engine) as session:
        jobs = JobRepository(session)
        job = jobs.add(
            CollectionJob(
                name="fetch", country_code="DE", entity_type=EntityType.PROGRAM, requested_limit=1
            )
        )
        service = FetchService(temp_settings, jobs, SourcePageRepository(session), fetcher)
        first = service.fetch_url(
            job.id, "https://example.test/page#fragment", SourceType.OFFICIAL_PROGRAM
        )
        second = service.fetch_url(job.id, "https://example.test/page", SourceType.OFFICIAL_PROGRAM)
        assert first.status is FetchStatus.FETCHED
        assert second.status is FetchStatus.CACHE_HIT
        assert calls["page"] == 1

        refreshed = service.fetch_url(
            job.id, "https://example.test/page", SourceType.OFFICIAL_PROGRAM, force_refresh=True
        )
        assert refreshed.status is FetchStatus.FETCHED
        assert calls["page"] == 2

        assert refreshed.cache_path
        refreshed.cache_path.write_bytes(b"corrupted")
        repaired = service.fetch_url(
            job.id, "https://example.test/page", SourceType.OFFICIAL_PROGRAM
        )
        assert repaired.status is FetchStatus.FETCHED
        assert calls["page"] == 3
        assert session.scalar(select(func.count()).select_from(SourcePageModel)) == 1
        page = SourcePageRepository(session).list_for_job(job.id)[0]
        assert page.http_status == 200
        assert page.content_hash == repaired.content_hash
    fetcher.close()
    engine.dispose()


def test_fetch_rejects_missing_job_without_network(temp_settings: Settings) -> None:
    calls = Counter()

    def handler(request: httpx.Request) -> httpx.Response:
        calls["all"] += 1
        return httpx.Response(200)

    engine = create_collector_engine(temp_settings.database_url)
    initialize_database(engine)
    fetcher = SafeHttpClient(
        temp_settings,
        transport=httpx.MockTransport(handler),
        resolver=public_resolver,
        sleep=lambda seconds: None,
    )
    with session_scope(engine) as session:
        service = FetchService(
            temp_settings, JobRepository(session), SourcePageRepository(session), fetcher
        )
        import uuid

        try:
            service.fetch_url(uuid.uuid4(), "https://example.test", SourceType.OFFICIAL_PROGRAM)
        except ValueError:
            pass
        else:
            raise AssertionError("missing job accepted")
    assert calls["all"] == 0
    fetcher.close()
    engine.dispose()


def test_fetch_failure_does_not_change_candidate_approval(temp_settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        return httpx.Response(404)

    engine = create_collector_engine(temp_settings.database_url)
    initialize_database(engine)
    fetcher = SafeHttpClient(
        temp_settings,
        transport=httpx.MockTransport(handler),
        resolver=public_resolver,
        sleep=lambda seconds: None,
    )
    with session_scope(engine) as session:
        jobs = JobRepository(session)
        job = jobs.add(
            CollectionJob(
                name="approval",
                country_code="DE",
                entity_type=EntityType.PROGRAM,
                requested_limit=1,
            )
        )
        candidate = CandidateRecord(
            job_id=job.id,
            entity_type=EntityType.PROGRAM,
            review_status=CandidateStatus.APPROVED,
            schema_version="1",
        )
        session.add(
            CandidateModel(
                id=str(candidate.id),
                job_id=str(job.id),
                entity_type=candidate.entity_type.value,
                review_status=candidate.review_status.value,
                schema_version="1",
                normalized_data={},
                created_at=candidate.created_at,
                updated_at=candidate.updated_at,
            )
        )
        session.commit()
        service = FetchService(temp_settings, jobs, SourcePageRepository(session), fetcher)
        result = service.fetch_url(job.id, "https://failure.test/page", SourceType.OFFICIAL_PROGRAM)
        assert result.status is FetchStatus.HTTP_ERROR
        session.expire_all()
        assert session.get(CandidateModel, str(candidate.id)).review_status == "approved"
    fetcher.close()
    engine.dispose()
