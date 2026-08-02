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
python -m pathfinder_collector program extract --job <job-uuid> --source <source-page-uuid>
python -m pathfinder_collector program extract --job <job-uuid> --source <supporting-source-uuid> --candidate <candidate-uuid>
python -m pathfinder_collector candidate list --job <job-uuid>
python -m pathfinder_collector candidate show <candidate-uuid>
python -m pathfinder_collector candidate blockers <candidate-uuid>
python -m pathfinder_collector candidate context <candidate-uuid> --apply-job-country
python -m pathfinder_collector candidate conflict-list <candidate-uuid>
python -m pathfinder_collector candidate conflict-resolve <conflict-uuid> --resolution clear-optional --reviewer local-1 --notes "Reason"
python -m pathfinder_collector candidate report <candidate-uuid>
python -m pathfinder_collector candidate review <candidate-uuid> --decision approve --reviewer local-1
python -m pathfinder_collector candidate history <candidate-uuid>
python -m pathfinder_collector candidate duplicates --job <job-uuid>
python -m pathfinder_collector export programs --job <job-uuid> --dry-run
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
templates do not establish nullability. No programme discovery, automated verification, web UI,
Pathfinder database integration, or AI feature exists.
Human approval remains mandatory before export.

Deterministic programme extraction operates only on already-cached official HTML. It creates
field-level evidence, surfaces conflicts, and produces an escaped local review report. See
`docs/EXTRACTION_POLICY.md` and `docs/PROGRAMME_FIELD_MAPPING.md`. Discovery, JavaScript-rendered
pages, PDFs, bulk crawling, and general university coverage remain out of scope.

Explicit local review can approve, reject, or return candidates for review while preserving
extraction evidence and append-only history. Only approved records can enter exact Pathfinder v1
CSV export packages. See `docs/REVIEW_WORKFLOW.md` and `docs/PATHFINDER_EXPORT.md`.

The controlled five-source Germany G1 exercise and its deliberately partial, zero-row approved
export are documented in `docs/pilots/GERMANY_G1_PILOT.md`.
