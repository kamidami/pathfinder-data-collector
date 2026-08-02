import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime

import httpx

from pathfinder_collector.config import Settings
from pathfinder_collector.enums import FetchStatus, RobotsStatus
from pathfinder_collector.fetching.cache import EvidenceCache
from pathfinder_collector.fetching.exceptions import ResponseTooLargeError, UnsafeUrlError
from pathfinder_collector.fetching.hashing import sha256_bytes
from pathfinder_collector.fetching.policies import HostRateLimiter
from pathfinder_collector.fetching.results import FetchResult
from pathfinder_collector.fetching.robots import RobotsChecker, bounded_retry_after
from pathfinder_collector.fetching.urls import (
    AddressResolver,
    SafeUrl,
    system_resolver,
    validate_url,
)

TEMPORARY_STATUSES = {408, 429, 500, 502, 503, 504}


class SafeHttpClient:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
        resolver: AddressResolver = system_resolver,
        sleep: Callable[[float], None] = time.sleep,
        max_attempts: int = 3,
    ) -> None:
        self.settings = settings
        self.resolver = resolver
        self.sleep = sleep
        self.max_attempts = max(1, min(max_attempts, 3))
        timeout = httpx.Timeout(
            connect=settings.connect_timeout_seconds,
            read=settings.read_timeout_seconds,
            write=settings.read_timeout_seconds,
            pool=settings.connect_timeout_seconds,
        )
        self.http = httpx.Client(
            headers={"User-Agent": settings.user_agent, "Accept": "text/html,text/plain"},
            timeout=timeout,
            follow_redirects=False,
            transport=transport,
        )
        self.cache = EvidenceCache(settings.cache_dir)
        self.limiter = HostRateLimiter(settings.min_host_delay_seconds, sleep=sleep)
        self.robots = RobotsChecker(self.http, settings, self.cache, self.limiter)
        self._fetch_lock = threading.Lock()

    def close(self) -> None:
        self.http.close()

    def fetch(self, url: str) -> FetchResult:
        # This phase intentionally serializes complete fetch operations. It is conservative and
        # guarantees that requests to the same host cannot overlap within this process.
        with self._fetch_lock:
            return self._fetch_serialized(url)

    def _fetch_serialized(self, url: str) -> FetchResult:
        try:
            target = validate_url(url, self.resolver)
        except UnsafeUrlError as exc:
            return self._error(
                url, FetchStatus.INVALID_URL, RobotsStatus.INVALID, "invalid_url", str(exc)
            )

        robots_status = self.robots.check(target)
        if robots_status is RobotsStatus.DISALLOWED:
            return self._error(
                url,
                FetchStatus.ROBOTS_DISALLOWED,
                robots_status,
                "robots_disallowed",
                "robots.txt disallows this page",
                target,
            )
        if robots_status in {RobotsStatus.UNAVAILABLE, RobotsStatus.INVALID}:
            return self._error(
                url,
                FetchStatus.ROBOTS_UNAVAILABLE,
                robots_status,
                "robots_unavailable",
                "robots.txt could not be evaluated safely",
                target,
            )
        return self._fetch_page(url, target, robots_status)

    def _fetch_page(
        self, requested_url: str, target: SafeUrl, robots_status: RobotsStatus
    ) -> FetchResult:
        redirects = 0
        while True:
            response_or_error = self._request_with_retries(target)
            if isinstance(response_or_error, FetchResult):
                response_or_error.requested_url = requested_url
                response_or_error.redirect_count = redirects
                response_or_error.robots_status = robots_status
                return response_or_error
            response = response_or_error
            if response.is_redirect:
                response.close()
                if redirects >= self.settings.max_redirects:
                    return self._error(
                        requested_url,
                        FetchStatus.HTTP_ERROR,
                        robots_status,
                        "too_many_redirects",
                        "maximum redirect count exceeded",
                        target,
                        redirects=redirects,
                    )
                location = response.headers.get("location")
                if not location:
                    return self._error(
                        requested_url,
                        FetchStatus.HTTP_ERROR,
                        robots_status,
                        "invalid_redirect",
                        "redirect did not provide a destination",
                        target,
                        redirects=redirects,
                    )
                try:
                    next_url = str(response.url.join(location))
                    target = validate_url(next_url, self.resolver)
                except UnsafeUrlError as exc:
                    return self._error(
                        requested_url,
                        FetchStatus.INVALID_URL,
                        robots_status,
                        "unsafe_redirect",
                        str(exc),
                        redirects=redirects + 1,
                    )
                robots_status = self.robots.check(target)
                if robots_status is not RobotsStatus.ALLOWED:
                    status = (
                        FetchStatus.ROBOTS_DISALLOWED
                        if robots_status is RobotsStatus.DISALLOWED
                        else FetchStatus.ROBOTS_UNAVAILABLE
                    )
                    return self._error(
                        requested_url,
                        status,
                        robots_status,
                        status.value,
                        "redirect destination is not allowed by robots policy",
                        target,
                        redirects=redirects + 1,
                    )
                redirects += 1
                continue
            return self._consume(response, requested_url, target, robots_status, redirects)

    def _request_with_retries(self, target: SafeUrl) -> httpx.Response | FetchResult:
        for attempt in range(self.max_attempts):
            self.limiter.wait(target.host)
            try:
                request = self.http.build_request("GET", target.fetch_url)
                response = self.http.send(request, stream=True)
            except (httpx.TimeoutException, httpx.NetworkError):
                if attempt + 1 < self.max_attempts:
                    continue
                return self._error(
                    target.fetch_url,
                    FetchStatus.NETWORK_ERROR,
                    RobotsStatus.ALLOWED,
                    "network_error",
                    "request failed after bounded retries",
                    target,
                )
            if response.status_code in TEMPORARY_STATUSES and attempt + 1 < self.max_attempts:
                retry_after = bounded_retry_after(response.headers.get("retry-after"))
                response.close()
                if retry_after:
                    self.sleep(retry_after)
                continue
            return response
        raise AssertionError("bounded retry loop did not return")

    def _consume(
        self,
        response: httpx.Response,
        requested_url: str,
        target: SafeUrl,
        robots_status: RobotsStatus,
        redirects: int,
    ) -> FetchResult:
        status_code = response.status_code
        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if status_code >= 400:
            response.close()
            return self._error(
                requested_url,
                FetchStatus.HTTP_ERROR,
                robots_status,
                f"http_{status_code}",
                "server returned an HTTP error",
                target,
                http_status=status_code,
                redirects=redirects,
            )
        if content_type not in self.settings.allowed_content_type_set:
            response.close()
            return self._error(
                requested_url,
                FetchStatus.UNSUPPORTED_CONTENT,
                robots_status,
                "unsupported_content_type",
                "response content type is not allowed",
                target,
                http_status=status_code,
                redirects=redirects,
            )
        try:
            content = self._read_bounded(response)
        except ResponseTooLargeError as exc:
            return self._error(
                requested_url,
                FetchStatus.RESPONSE_TOO_LARGE,
                robots_status,
                "response_too_large",
                str(exc),
                target,
                http_status=status_code,
                redirects=redirects,
            )
        except httpx.HTTPError:
            return self._error(
                requested_url,
                FetchStatus.NETWORK_ERROR,
                robots_status,
                "network_error",
                "response stream failed",
                target,
                http_status=status_code,
                redirects=redirects,
            )
        content_hash = sha256_bytes(content)
        cache_path = self.cache.page_path(target.host, content_hash, content_type)
        try:
            self.cache.atomic_write(cache_path, content)
        except OSError:
            return self._error(
                requested_url,
                FetchStatus.NETWORK_ERROR,
                robots_status,
                "cache_write_error",
                "response could not be stored safely",
                target,
                http_status=status_code,
                redirects=redirects,
            )
        fetched_at = datetime.now(UTC)
        return FetchResult(
            requested_url=requested_url,
            final_normalized_url=target.normalized_url,
            safe_display_url=target.safe_display,
            status=FetchStatus.FETCHED,
            http_status=status_code,
            content_type=content_type,
            response_bytes=len(content),
            content_hash=content_hash,
            cache_path=cache_path,
            fetched_at=fetched_at,
            robots_status=robots_status,
            redirect_count=redirects,
        )

    def _read_bounded(self, response: httpx.Response) -> bytes:
        content_length = response.headers.get("content-length")
        if content_length and content_length.isdigit():
            if int(content_length) > self.settings.max_response_bytes:
                response.close()
                raise ResponseTooLargeError("response exceeds configured maximum size")
        chunks: list[bytes] = []
        total = 0
        try:
            for chunk in response.iter_bytes():
                total += len(chunk)
                if total > self.settings.max_response_bytes:
                    raise ResponseTooLargeError("response exceeds configured maximum size")
                chunks.append(chunk)
        finally:
            response.close()
        return b"".join(chunks)

    @staticmethod
    def _error(
        requested_url: str,
        status: FetchStatus,
        robots_status: RobotsStatus,
        code: str,
        summary: str,
        target: SafeUrl | None = None,
        *,
        http_status: int | None = None,
        redirects: int = 0,
    ) -> FetchResult:
        return FetchResult(
            requested_url=requested_url,
            final_normalized_url=target.normalized_url if target else None,
            safe_display_url=target.safe_display if target else None,
            status=status,
            http_status=http_status,
            robots_status=robots_status,
            redirect_count=redirects,
            safe_error_code=code,
            safe_error_summary=summary[:500],
        )
