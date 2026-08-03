# Guided batch programme collection

Guided batch collection accepts a UTF-8 CSV for one existing programme job. The required column
is `source_url`; optional columns are `expected_university_name`, `expected_program_name`, and
`operator_notes`. Unknown columns and invalid rows reject the whole input before any fetch. Empty
rows are ignored and validation messages include CSV row numbers.

```csv
source_url,expected_university_name,expected_program_name,operator_notes
https://university.example.invalid/programmes/data-science,Example University,Data Science,Check title
```

Run:

```powershell
python -m pathfinder_collector batch collect --job-id <JOB_UUID> --file .\batch.csv
```

URLs are canonicalized and duplicate input URLs are skipped. Processing is sequential and
continues after controlled fetch or extraction failures. Existing URLs for the same job are
reported as `already_existing` and are not fetched or extracted again, making reruns idempotent.
Other result statuses are the existing fetch/extraction statuses, including `fetch_failed`,
`extracted`, `partial`, and safe unsupported/no-data outcomes.

Operator expectations are hints only. They are labelled as operator context in reports and never
replace official extracted evidence. New candidates retain the extractor's safe status and are
never approved, verified, exported, or imported automatically. Human review remains mandatory.
Robots exclusions, HTTP access failures, unsafe redirects, private-network protection, content
limits, and other safe-fetch restrictions are never bypassed.

Each run writes ignored runtime files beneath
`var/reports/batches/<batch-run-id>/`: `batch_summary.json`, `batch_results.csv`, and
`batch_report.txt`. Reports omit HTML, cache paths, credentials, secrets, database URLs, and stack
traces. Formula-like CSV report cells are escaped for spreadsheet safety.
