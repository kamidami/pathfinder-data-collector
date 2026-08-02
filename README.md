# Pathfinder Data Collector

A small, standalone Python application for collecting, reviewing, validating, and exporting
evidence-backed university programme data. It is intentionally separate from Pathfinder: it
does not import Pathfinder code or connect to Pathfinder databases. Integration happens only
through versioned CSV contracts.

## Architecture

The `src/pathfinder_collector` package separates domain models, persistence, source-adapter
interfaces, services, and export contracts. SQLite is local collector state. Alembic owns the
schema. `contracts/pathfinder/v1` is the immutable integration boundary. See
`docs/ARCHITECTURE.md` and `docs/DATA_FLOW.md`.

## Install and use

Python 3.11 or newer is required.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pathfinder_collector doctor
python -m pathfinder_collector init-db
python -m pathfinder_collector contract list
python -m pathfinder_collector contract show programs
python -m pathfinder_collector job create --name germany-g1 --country DE --entity program --limit 5
python -m pathfinder_collector job list
python -m pathfinder_collector source fetch --job <job-uuid> --url https://example.edu/page --type official_program
python -m pathfinder_collector source list --job <job-uuid>
```

Configuration uses `PATHFINDER_COLLECTOR_` environment variables; copy `.env.example` for
local overrides. Relative database and runtime paths resolve from the repository root. Runtime
state is written beneath `var/cache`, `var/exports`, and `var/reports` and is ignored by Git.

## Safe fetching

The collector provides a policy-conscious HTTP fetcher with SSRF protection, robots checks,
bounded retries and response sizes, per-host delays, and an ignored evidence cache. Fetch results
store metadata in collector-owned SQLite without storing raw HTML in database rows. See
`docs/FETCHING_POLICY.md` for exact behavior.

## Data contract and limitations

The v1 templates preserve Pathfinder's observed CSV headers and order. The manifest records
their provenance. Required fields are deliberately left unspecified because header-only source
templates do not establish nullability. No programme discovery, structured field extraction,
automated verification, web UI, Pathfinder database integration, or AI feature exists yet.
Human approval remains mandatory before export.
