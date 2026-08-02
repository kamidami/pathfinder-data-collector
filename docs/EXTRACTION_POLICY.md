# Programme extraction policy

Extraction runs only against a successful `SourcePage` and its intact cached HTML. It never
fetches, executes scripts, loads subresources, evaluates JavaScript, follows links, or parses
PDFs. HTML bytes and node counts are bounded, malformed markup is recovered conservatively,
and invalid or oversized JSON-LD is ignored with a warning.

Deterministic evidence priority is: explicit JSON-LD programme properties; labelled definition
lists and tables; programme-context `h1`; then standard metadata fallbacks. Navigation, headers,
footers, forms, scripts, hidden content, and unrelated marketing paragraphs are excluded where
practical. Page language is never evidence of teaching language. Country is not inferred from a
top-level domain, and city is not inferred from a contact address.

Each extracted value gets a bounded `EvidenceRecord` containing its original value, normalized
value where supported, structural locator, short excerpt, confidence, and exact source page.
High confidence means explicit structured or labelled evidence; medium means a controlled
metadata or heading heuristic; low means review-worthy context and is excluded from normalized
candidate data. Confidence is not verification.

Equal-priority contradictory normalized values create an unresolved conflict and are omitted
from normalized data. A lower-priority contradiction is retained as evidence and a warning.
Extraction-owned evidence and conflicts are replaced idempotently on rerun; human statuses and
unrelated candidates are not overwritten.

A candidate becomes `collected` only when programme name, university, degree, teaching language,
and source URL are present without conflicts or low-confidence values. Otherwise it becomes
`needs_review`. Automatic extraction never approves, exports, or verifies a candidate.

The local review report escapes all untrusted text and includes no scripts, remote assets, raw
HTML, response headers, or cache paths. Reports are ignored runtime artifacts and explicitly warn
that human approval is required.

