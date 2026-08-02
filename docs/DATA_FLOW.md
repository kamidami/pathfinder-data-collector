# Data flow

1. A human creates a pending collection job.
2. A requested official URL passes SSRF validation and robots review.
3. The safe fetcher retrieves bounded HTML/text or reuses an intact, unexpired cache entry.
4. Raw content is hashed into ignored cache storage and bounded source metadata enters SQLite.
5. Deterministic extraction reads one intact cached programme page, creates normalized candidate
   fields with field-level evidence, and exposes conflicts.
6. A human reviews candidates; automation never marks them verified or approved.
7. Approved records are validated against a versioned contract and exported as CSV.
8. Pathfinder may consume that CSV through its own import process; there is no database link.
