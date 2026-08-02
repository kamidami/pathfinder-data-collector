# Architecture

This repository is an independent application. Domain Pydantic models express collector state;
SQLAlchemy models and repositories persist it in collector-owned SQLite; Typer exposes explicit
operations; adapter protocols define a future collection boundary; versioned CSV files are the
only Pathfinder integration mechanism.

Dependencies point inward: CLI and adapters use services/domain abstractions, while persistence
implements storage. The collector never imports Pathfinder modules and never opens a Pathfinder
SQLite or PostgreSQL database.

The `fetching` package separates URL safety, HTTP behavior, robots policy, rate limiting,
hashing, cache files, and result types. `FetchService` validates jobs and coordinates this layer
with `SourcePageRepository`; the CLI contains no direct HTTP calls. Raw responses remain only in
ignored runtime cache while bounded metadata is persisted in SQLite.

The `extraction` package parses untrusted cached HTML without networking and separates metadata,
label handling, normalization, evidence, confidence, and result models. The programme extraction
service owns idempotent candidate/evidence/conflict persistence. Report generation reads these
bounded records and writes escaped, script-free HTML under ignored runtime storage.

`candidate_sources` identifies one retained primary source and any explicitly attached supporting
sources. Supporting extraction is an operator-directed operation: it replaces evidence only for
that candidate/source/version tuple, then deterministically recomputes effective values and
cross-source conflicts. It never discovers pages or creates a second candidate implicitly.

Human review is a transactional service boundary with append-only decisions and separately stored
overrides. Export validation maps effective approved programme values into copied Pathfinder v1
contracts, writes atomic ignored packages, and records immutable run/file/candidate history.

Operator job context is stored separately in `candidate_context_values`; it is never represented
as SourcePage evidence. `context_conflicts` blocks context contradicted by official evidence.
Explicit evidence-conflict decisions update only effective reviewer overrides while append-only
`conflict_resolutions` records retain the reviewer, action, selected value, reason, and timestamp.
