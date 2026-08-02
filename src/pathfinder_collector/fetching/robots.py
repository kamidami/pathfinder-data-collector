from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.robotparser import RobotFileParser

import httpx

from pathfinder_collector.config import Settings
from pathfinder_collector.enums import RobotsStatus
from pathfinder_collector.fetching.cache import EvidenceCache
from pathfinder_collector.fetching.policies import HostRateLimiter
from pathfinder_collector.fetching.urls import SafeUrl


class RobotsChecker:
    def __init__(
        self,
        client: httpx.Client,
        settings: Settings,
        cache: EvidenceCache,
        limiter: HostRateLimiter,
    ) -> None:
        self.client = client
        self.settings = settings
        self.cache = cache
        self.limiter = limiter

    def check(self, target: SafeUrl) -> RobotsStatus:
        robots_url = f"{target.origin}/robots.txt"
        cache_path = self.cache.robots_path(target.origin)
        content = self._cached(cache_path)
        if content is None:
            try:
                self.limiter.wait(target.host)
                request = self.client.build_request("GET", robots_url)
                response = self.client.send(request, stream=True)
            except httpx.HTTPError:
                return RobotsStatus.UNAVAILABLE
            try:
                if response.status_code in {401, 403}:
                    return RobotsStatus.DISALLOWED
                if response.status_code == 429 or response.status_code >= 500:
                    return RobotsStatus.UNAVAILABLE
                if 400 <= response.status_code < 500:
                    content = b""
                elif response.status_code == 200:
                    chunks: list[bytes] = []
                    total = 0
                    for chunk in response.iter_bytes():
                        total += len(chunk)
                        if total > 512 * 1024:
                            return RobotsStatus.INVALID
                        chunks.append(chunk)
                    content = b"".join(chunks)
                    self.cache.atomic_write(cache_path, content)
                else:
                    return RobotsStatus.UNAVAILABLE
            except (httpx.HTTPError, OSError):
                return RobotsStatus.UNAVAILABLE
            finally:
                response.close()
        try:
            parser = RobotFileParser()
            parser.set_url(robots_url)
            parser.parse(content.decode("utf-8", errors="replace").splitlines())
            allowed = parser.can_fetch(self.settings.user_agent, target.fetch_url)
        except (TypeError, ValueError):
            return RobotsStatus.INVALID
        return RobotsStatus.ALLOWED if allowed else RobotsStatus.DISALLOWED

    def _cached(self, path: object) -> bytes | None:
        try:
            cache_path = path
            age = datetime.now(UTC) - datetime.fromtimestamp(cache_path.stat().st_mtime, UTC)
            if age <= timedelta(hours=self.settings.robots_cache_ttl_hours):
                return cache_path.read_bytes()
        except OSError:
            return None
        return None


def bounded_retry_after(value: str | None, maximum: float = 30.0) -> float | None:
    if not value:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            when = parsedate_to_datetime(value)
            if when.tzinfo is None:
                when = when.replace(tzinfo=UTC)
            seconds = (when - datetime.now(UTC)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return None
    return min(maximum, max(0.0, seconds))
