import threading
import time
from collections.abc import Callable


class HostRateLimiter:
    """Process-local serialized per-host politeness limiter."""

    def __init__(
        self,
        minimum_delay: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.minimum_delay = minimum_delay
        self.clock = clock
        self.sleep = sleep
        self._locks: dict[str, threading.Lock] = {}
        self._last_request: dict[str, float] = {}
        self._guard = threading.Lock()

    def wait(self, host: str) -> None:
        with self._guard:
            lock = self._locks.setdefault(host, threading.Lock())
        with lock:
            elapsed = self.clock() - self._last_request.get(host, float("-inf"))
            remaining = self.minimum_delay - elapsed
            if remaining > 0:
                self.sleep(remaining)
            self._last_request[host] = self.clock()
