from collections import Counter

import httpx

from pathfinder_collector.config import Settings
from pathfinder_collector.enums import FetchStatus, RobotsStatus
from pathfinder_collector.fetching.cache import EvidenceCache
from pathfinder_collector.fetching.client import SafeHttpClient
from pathfinder_collector.fetching.hashing import sha256_bytes


def public_resolver(host: str) -> list[str]:
    return ["93.184.216.34"]


def client(settings: Settings, handler: object, **kwargs: object) -> SafeHttpClient:
    return SafeHttpClient(
        settings,
        transport=httpx.MockTransport(handler),
        resolver=public_resolver,
        sleep=lambda seconds: None,
        **kwargs,
    )


def allow_robots(request: httpx.Request) -> httpx.Response | None:
    if request.url.path == "/robots.txt":
        return httpx.Response(200, text="User-agent: *\nAllow: /\n")
    return None


def test_normal_html_fetch_and_stable_hash(temp_settings: Settings) -> None:
    body = b"<html><title>Example</title></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        return allow_robots(request) or httpx.Response(
            200, headers={"content-type": "text/html"}, content=body
        )

    fetcher = client(temp_settings, handler)
    result = fetcher.fetch("https://example.test/program?lang=en")
    assert result.status is FetchStatus.FETCHED
    assert result.robots_status is RobotsStatus.ALLOWED
    assert result.content_hash == sha256_bytes(body)
    assert result.cache_path and result.cache_path.read_bytes() == body
    fetcher.close()


def test_robots_disallowed_does_not_fetch_page(temp_settings: Settings) -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        return httpx.Response(200, text="User-agent: *\nDisallow: /private\n")

    fetcher = client(temp_settings, handler)
    result = fetcher.fetch("https://example.test/private/page")
    assert result.status is FetchStatus.ROBOTS_DISALLOWED
    assert requests == ["/robots.txt"]
    fetcher.close()


def test_robots_unavailable_on_timeout(temp_settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    fetcher = client(temp_settings, handler)
    result = fetcher.fetch("https://example.test/page")
    assert result.status is FetchStatus.ROBOTS_UNAVAILABLE
    fetcher.close()


def test_page_timeout_returns_controlled_network_error(temp_settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if response := allow_robots(request):
            return response
        raise httpx.ReadTimeout("timeout", request=request)

    fetcher = client(temp_settings, handler)
    result = fetcher.fetch("https://timeout.test/page")
    assert result.status is FetchStatus.NETWORK_ERROR
    assert result.safe_error_code == "network_error"
    fetcher.close()


def test_temporary_failure_retried(temp_settings: Settings) -> None:
    calls = Counter()

    def handler(request: httpx.Request) -> httpx.Response:
        if response := allow_robots(request):
            return response
        calls["page"] += 1
        if calls["page"] == 1:
            return httpx.Response(503)
        return httpx.Response(200, headers={"content-type": "text/plain"}, text="ok")

    fetcher = client(temp_settings, handler)
    result = fetcher.fetch("https://example.test/page")
    assert result.status is FetchStatus.FETCHED
    assert calls["page"] == 2
    fetcher.close()


def test_429_retried_and_permanent_404_not_retried(temp_settings: Settings) -> None:
    statuses = iter([429, 200])
    page_calls = Counter()

    def retry_handler(request: httpx.Request) -> httpx.Response:
        if response := allow_robots(request):
            return response
        page_calls["retry"] += 1
        status = next(statuses)
        return httpx.Response(status, headers={"content-type": "text/plain", "retry-after": "0"})

    fetcher = client(temp_settings, retry_handler)
    assert fetcher.fetch("https://example.test/retry").status is FetchStatus.FETCHED
    assert page_calls["retry"] == 2
    fetcher.close()

    def not_found_handler(request: httpx.Request) -> httpx.Response:
        if response := allow_robots(request):
            return response
        page_calls["404"] += 1
        return httpx.Response(404)

    fetcher = client(temp_settings, not_found_handler)
    result = fetcher.fetch("https://other.test/missing")
    assert result.status is FetchStatus.HTTP_ERROR
    assert page_calls["404"] == 1
    fetcher.close()


def test_allowed_redirect_and_private_redirect_rejected(temp_settings: Settings) -> None:
    def allowed_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        if request.url.host == "example.test":
            return httpx.Response(302, headers={"location": "https://other.test/final"})
        return httpx.Response(200, headers={"content-type": "text/html"}, text="done")

    fetcher = client(temp_settings, allowed_handler)
    result = fetcher.fetch("https://example.test/start")
    assert result.status is FetchStatus.FETCHED
    assert result.redirect_count == 1
    assert result.final_normalized_url == "https://other.test/final"
    fetcher.close()

    def private_handler(request: httpx.Request) -> httpx.Response:
        if response := allow_robots(request):
            return response
        return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})

    fetcher = client(temp_settings, private_handler)
    result = fetcher.fetch("https://third.test/start")
    assert result.status is FetchStatus.INVALID_URL
    assert result.safe_error_code == "unsafe_redirect"
    fetcher.close()


def test_unsupported_content_and_size_limit(temp_settings: Settings) -> None:
    def binary(request: httpx.Request) -> httpx.Response:
        return allow_robots(request) or httpx.Response(
            200, headers={"content-type": "application/pdf"}, content=b"pdf"
        )

    fetcher = client(temp_settings, binary)
    assert fetcher.fetch("https://example.test/file").status is FetchStatus.UNSUPPORTED_CONTENT
    fetcher.close()

    temp_settings.max_response_bytes = 3

    def large(request: httpx.Request) -> httpx.Response:
        return allow_robots(request) or httpx.Response(
            200, headers={"content-type": "text/plain"}, content=b"four"
        )

    fetcher = client(temp_settings, large)
    assert fetcher.fetch("https://large.test/page").status is FetchStatus.RESPONSE_TOO_LARGE
    fetcher.close()


def test_cache_paths_are_safe_and_writes_atomic(temp_settings: Settings) -> None:
    cache = EvidenceCache(temp_settings.cache_dir)
    path = cache.page_path("../../unsafe.example", "a" * 64, "text/html")
    assert "unsafe.example" not in str(path)
    assert path.name == f"{'a' * 64}.html"
    cache.atomic_write(path, b"first")
    cache.atomic_write(path, b"second")
    assert path.read_bytes() == b"second"
    assert not list(path.parent.glob(".tmp-*"))
