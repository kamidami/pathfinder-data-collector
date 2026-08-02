# Pathfinder v1 CSV export

The exporter reads only the copied local contract manifest and templates. It never imports
Pathfinder code, opens a Pathfinder database, or writes into Pathfinder directories.

Each successful run creates an ignored `var/exports/<run-uuid>/` package containing:

- `programs.csv` with the exact Pathfinder v1 programmes header and column order;
- `source_records.csv` with the exact v1 source-record header and order;
- `manifest.json` with version, run, candidate, status, warning, and SHA-256 metadata;
- `validation_report.txt` with counts, errors, warnings, and duplicate results.

Only explicitly human-approved programme candidates are eligible. `exported` candidates remain
eligible for repeat, auditable exports because that status implies prior approval. Collected,
needs-review, and rejected candidates are skipped. Unresolved conflicts, invalid effective data,
missing sources, missing or non-canonical field classifications, unmapped country/source values,
invalid dates/URLs, and exact duplicate programme keys block export.

CSV is UTF-8, uses standard quoting and CRLF line endings, preserves missing values as blank, and
prefixes spreadsheet-formula-leading cells with an apostrophe. Unsupported fields—including
tuition, deadlines, requirements, scores, documents, and scholarships—remain blank. The
`data_status` value is conservatively `collected`, never `verified`.
Country values are mapped from the collector's ISO alpha-2 codes to Pathfinder's alpha-3 codes.
Collector source types are explicitly mapped to Pathfinder's source enum. Both programme and
source rows receive the human approval date as `last_verified_date`; this means reviewed by the
collector operator, not independently verified by Pathfinder.

```powershell
python -m pathfinder_collector candidate duplicates --job <job-id>
python -m pathfinder_collector export programs --job <job-id> --dry-run
python -m pathfinder_collector export programs --job <job-id> --name reviewed-germany
python -m pathfinder_collector export show <export-run-id>
python -m pathfinder_collector contract compatibility-check --pathfinder-root C:\path\to\pathfinder
```

Dry-run validates without creating a package or changing candidate state. To import, inspect the
manifest and validation report, then use Pathfinder's normal administrator CSV import screen to
upload `programs.csv` and `source_records.csv` in the order required by that admin workflow. Do
not copy files into Pathfinder internals or write its database directly.

For an approved multi-source candidate, `source_records.csv` contains one deduplicated row per
attached official source. `programs.csv` retains the primary canonical source URL. Neither file
contains evidence excerpts or local cache locations.

The manifest includes counts of effective fields supplied by official source evidence, reviewer
overrides, and operator job context. Context may supply `programs.csv.country_code`, but it never
creates a `source_records.csv` row. Conflict-cleared optional fields remain blank and
`data_status` remains `collected`, never `verified`.

The compatible Germany G1 replacement is export run
`466ae466-41f3-4a58-ad56-0d50e3d3419c`, labelled
`germany-g1-pathfinder-compatible`. Earlier G1 packages are superseded and must not be imported.
