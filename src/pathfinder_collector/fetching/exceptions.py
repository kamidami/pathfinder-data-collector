class FetchingError(Exception):
    """Base class for controlled fetching failures."""


class UnsafeUrlError(FetchingError):
    """URL failed SSRF validation."""


class ResponseTooLargeError(FetchingError):
    """Response exceeded the configured byte limit."""
