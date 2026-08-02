import pytest

from pathfinder_collector.fetching.exceptions import UnsafeUrlError
from pathfinder_collector.fetching.urls import validate_url


def public_resolver(host: str) -> list[str]:
    return ["93.184.216.34"]


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/page",
        "http://localhost.example.com@127.0.0.1/page",
        "http://10.0.0.1/page",
        "http://127.1/page",
        "http://[::1]/page",
        "http://[fe80::1]/page",
        "file:///etc/passwd",
        "https://user:password@example.test/page",
    ],
)
def test_blocked_urls(url: str) -> None:
    with pytest.raises(UnsafeUrlError):
        validate_url(url, public_resolver)


def test_hostname_resolving_private_is_blocked() -> None:
    with pytest.raises(UnsafeUrlError):
        validate_url("https://public-looking.test/page", lambda host: ["192.168.1.2"])


def test_normalization_removes_fragment_but_keeps_query() -> None:
    result = validate_url("HTTPS://EXAMPLE.TEST:443/a?q=1#part", public_resolver)
    assert result.normalized_url == "https://example.test/a?q=1"
    assert result.safe_display == "https://example.test/a"
