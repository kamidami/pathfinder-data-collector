import ipaddress
import socket
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from urllib.parse import SplitResult, urlsplit, urlunsplit

from pathfinder_collector.fetching.exceptions import UnsafeUrlError

MAX_URL_LENGTH = 4096
AddressResolver = Callable[[str], Iterable[str]]


@dataclass(frozen=True)
class SafeUrl:
    fetch_url: str
    normalized_url: str
    origin: str
    host: str
    safe_display: str


def system_resolver(host: str) -> Iterable[str]:
    return {item[4][0] for item in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)}


def _is_blocked_address(value: str) -> bool:
    address = ipaddress.ip_address(value)
    return not address.is_global


def validate_url(url: str, resolver: AddressResolver = system_resolver) -> SafeUrl:
    if len(url) > MAX_URL_LENGTH:
        raise UnsafeUrlError("URL exceeds the maximum length")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise UnsafeUrlError("URL is malformed") from exc
    if parts.scheme.lower() not in {"http", "https"}:
        raise UnsafeUrlError("only HTTP and HTTPS URLs are allowed")
    if not parts.hostname:
        raise UnsafeUrlError("URL must contain a hostname")
    if parts.username is not None or parts.password is not None:
        raise UnsafeUrlError("embedded credentials are not allowed")
    host = parts.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith(".localhost"):
        raise UnsafeUrlError("local hostnames are blocked")
    if port is not None and not 1 <= port <= 65535:
        raise UnsafeUrlError("invalid port")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        if all(character.isdigit() or character == "." for character in host) or host.startswith(
            "0x"
        ):
            raise UnsafeUrlError("ambiguous numeric hostnames are blocked") from None
        try:
            addresses = tuple(resolver(host))
        except OSError as exc:
            raise UnsafeUrlError("hostname could not be safely resolved") from exc
        if not addresses:
            raise UnsafeUrlError("hostname did not resolve") from None
        if any(_is_blocked_address(address) for address in addresses):
            raise UnsafeUrlError("hostname resolves to a blocked network address") from None
    else:
        if not literal.is_global:
            raise UnsafeUrlError("private or non-public network addresses are blocked")
    scheme = parts.scheme.lower()
    host_for_netloc = f"[{host}]" if ":" in host else host
    default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    netloc = host_for_netloc if port is None or default_port else f"{host_for_netloc}:{port}"
    path = parts.path or "/"
    normalized = urlunsplit(SplitResult(scheme, netloc, path, parts.query, ""))
    origin = urlunsplit(SplitResult(scheme, netloc, "", "", ""))
    display = urlunsplit(SplitResult(scheme, netloc, path, "", ""))
    return SafeUrl(normalized, normalized, origin, host, display)
