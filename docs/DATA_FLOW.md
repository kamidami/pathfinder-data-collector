# Data flow

1. A human creates a pending collection job.
2. A requested official URL passes SSRF validation and robots review.
3. The safe fetcher retrieves bounded HTML/text or reuses an intact, unexpired cache entry.
4. Raw content is hashed into ignored cache storage and bounded source metadata enters SQLite.
5. Deterministic extraction reads an intact cached programme page, creates normalized candidate
   fields with field-level evidence, and exposes conflicts. An operator may explicitly attach a
   fetched official supporting page to the same candidate; the primary relationship and evidence
   from every source are retained.
6. A human explicitly approves, rejects, or returns a candidate; extraction never approves it.
7. Effective approved values are validated, duplicate-checked, and exported to an ignored,
   versioned CSV package with manifest and validation report.
8. Pathfinder may consume that CSV through its own import process; there is no database link.
