# Safe fetching policy

The fetcher accepts only public HTTP and HTTPS URLs. It rejects credentials in URLs, local and
private hosts, non-global IPv4/IPv6 addresses, deceptive local hostnames, excessive URL length,
and hostnames that resolve to any blocked address. Every redirect is resolved, validated, and
checked against robots rules before its page is requested. Query parameters may be needed for
fetching, but CLI output omits them.

Before page retrieval, the collector requests and caches `robots.txt` by origin. Explicitly
disallowed pages are not fetched. Temporary robots failures produce a review-needed result,
not implicit permission. A missing robots file permits fetching under the parser convention,
but robots permission is neither legal permission nor permission to reproduce or reuse content;
site terms must be reviewed before bulk collection.

Requests identify the collector, use bounded connect/read timeouts, and are serialized per host
with a configurable minimum delay. The limiter is process-local, not distributed. At most three
attempts are made for connection failures, 408, 429, and selected 5xx responses. Permanent 4xx
responses are not retried. A valid bounded `Retry-After` is respected.

Only configured HTML and plain-text media types are accepted. Responses are streamed and
stopped above the default 5 MiB decoded-content limit, including compressed responses. Raw
content is SHA-256 hashed and atomically stored under ignored `var/cache` paths with safe,
deterministic names. SQLite stores bounded metadata, never page bodies. Fresh, intact cache
entries avoid network requests; missing or corrupted files are refetched.

This phase retrieves evidence pages only. It does not discover programmes, extract fields,
verify sources, approve candidates, interpret terms, or commit external pages.

