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

Human review is a transactional service boundary with append-only decisions and separately stored
overrides. Export validation maps effective approved programme values into copied Pathfinder v1
contracts, writes atomic ignored packages, and records immutable run/file/candidate history.
