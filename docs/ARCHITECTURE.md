# Architecture

This repository is an independent application. Domain Pydantic models express collector state;
SQLAlchemy models and repositories persist it in collector-owned SQLite; Typer exposes explicit
operations; adapter protocols define a future collection boundary; versioned CSV files are the
only Pathfinder integration mechanism.

Dependencies point inward: CLI and adapters use services/domain abstractions, while persistence
implements storage. The collector never imports Pathfinder modules and never opens a Pathfinder
SQLite or PostgreSQL database.

