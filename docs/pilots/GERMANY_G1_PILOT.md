# Germany G1 five-programme pilot

Pilot date: 2026-08-02  
Collector version: 0.1.0, base commit `7b47207`  
Job: `germany-g1-pilot` (`DE`, `program`, requested limit 5)

This was a controlled five-page exercise, not a claim of statistical accuracy or support for
all German universities. Human approval in this collector is distinct from official
verification in Pathfinder.

## Sources and outcomes

The pages were processed serially. Robots checks were performed by the safe fetcher before
each page request. No optional supporting page was used and no linked page was crawled.

| Programme | Official primary URL | Robots | Fetch | Automatic fields | Automatic core fields | Evidence | Conflicts | Overrides | Final status | Export eligible | Review |
|---|---|---|---|---:|---:|---:|---:|---:|---|---|---:|
| TUM — Data Engineering and Analytics | https://www.tum.de/en/studies/degree-programs/detail/data-engineering-and-analytics-master-of-science-msc | allowed | HTTP 200, fetched, cache miss | 10/14 | 4/5 | 15 | 0 | 0 | needs_review | no | ~4 min |
| RWTH Aachen — Data Science | https://www.rwth-aachen.de/cms/root/studium/vor-dem-studium/studiengaenge/liste-aktuelle-studiengaenge/studiengangbeschreibung/~pzpc/data-science-m-sc/?lidx=1 | allowed | HTTP 200, fetched, cache miss | 5/14 | 5/5 | 6 | 0 | 0 | needs_review | no | ~3 min |
| University of Stuttgart — Computer Science | https://www.uni-stuttgart.de/en/study/study-programs/Computer-Science-M.Sc.-00001/ | allowed | HTTP 200, fetched, cache miss | 8/14 | 5/5 | 8 | 0 | 0 | needs_review | no | ~4 min |
| TU Berlin — Computer Science (Informatik) | https://www.tu.berlin/en/studying/study-programs/all-programs-offered/study-course/computer-science-informatik-m-sc | allowed | HTTP 403, permanent failure | 0/14 | 0/5 | 0 | 0 | 0 | no candidate | no | ~1 min |
| Saarland University — Data Science and Artificial Intelligence | https://www.uni-saarland.de/en/study/programmes/master/data-science.html | allowed | HTTP 200, fetched, cache miss | 8/14 | 5/5 | 8 | 0 | 0 | needs_review | no | ~3 min |

The five extraction-core fields used above are programme name, university name, degree level,
teaching language, and source URL. Approval additionally requires country code. Candidate
reports recorded the short evidence, missing fields,
conflicts, and review history. The TUM candidate lacked extracted teaching-language evidence.
The RWTH, Stuttgart, and Saarland candidates lacked explicit country evidence. Those values
were not inferred from the job country, host name, page language, or memory. TU Berlin's 403
was not retried or bypassed. Review notes explicitly returned all four candidates to review.

## Metrics

- Fetch success: 4/5 (80.0%).
- Extraction success: 4/5 (80.0%).
- Automatic core-field completion: 3/5 fully complete (60.0%); across all extraction-core field
  slots, 19/25 were supported (76.0%).
- Automatic supported-field completion: 31/70 (44.3%).
- Average evidence count: 7.4 per input.
- Override rate: 0/5 (0.0%).
- Conflict rate after normalization: 0/5 (0.0%).
- Approval and export rates: 0/5 (0.0%).
- Approximate average review time: 3.0 minutes.
- Safe failure categories: one `http_403`; one candidate missing explicit teaching-language
  evidence; three candidates missing explicit country evidence.

These descriptive measurements apply only to these five inputs.

## Generic defects and fixes

The pilot exposed reusable HTML patterns that the extractor did not represent safely:

- labelled cards and values split across adjacent paragraphs;
- multiple `Label: value` pairs separated by `br` elements;
- degree context placed adjacent to, rather than inside, the main heading;
- conservative institution metadata in JSON-LD and standard author/title metadata;
- equivalent ISO-8601 month and semester durations producing a false conflict; and
- query strings being retained in a candidate's canonical source URL.

The extractor now handles those structures generically, keeps bounded evidence locators, and
normalizes `P24M` to four semesters when the ISO value is exactly divisible into semesters.
Explicit prose such as `24 months` remains months. Minimal synthetic fixtures reproduce the
card and inline-label patterns; no downloaded university page is committed. No domain adapter,
hard-coded programme result, discovery mechanism, AI extraction, or migration was added.

Remaining source-specific limitations are deliberate. The current evidence model cannot
safely derive a country merely from a `.de` host or the pilot job, and it does not reinterpret
admission-language requirements as teaching language. The TU Berlin server denied the normal
HTTP request. Optional multi-source attachment was therefore not exercised in this run.

## Review and export

### Compatibility hotfix (2026-08-02)

Four candidates were subsequently approved under the operator-context workflow. A human reviewer
classified RWTH Data Science, Saarland Data Science and Artificial Intelligence, and TUM Data
Engineering and Analytics as `Data Science / AI`, and Stuttgart Computer Science as
`Computer Science / IT`. These are reviewer overrides with review notes, not hard-coded
programme mappings.

The replacement package is
`var/exports/466ae466-41f3-4a58-ad56-0d50e3d3419c/`, labelled
`germany-g1-pathfinder-compatible`. It contains four programme rows and six deduplicated source
rows. Programme identity keys and source URLs each have zero duplicate groups. It emits `DEU`,
Pathfinder's `program` source type, and `2026-08-02` review dates. All earlier G1 packages are
superseded and must not be imported.

The read-only contract compatibility check passed against the real Pathfinder checkout. The real
Pathfinder management command uses `--template` (not `--entity`). Both importer dry-runs passed
against a disposable copy of the Pathfinder SQLite database, leaving the live database and
repository untouched:

```text
Dry run passed for 4 row(s). No data was saved.
Dry run passed for 6 row(s). No data was saved.
```

The original Task 0.5 dry-run selected zero approved records and clearly skipped four
needs-review candidates.
The real export did the same and generated a contract-valid, header-only package at:

`var/exports/eb5f2351-11e0-48f3-b4df-28ae108f3239/`

It contains `programs.csv`, `source_records.csv`, `manifest.json`, and
`validation_report.txt`. The manifest records zero candidates, four warnings, Pathfinder v1,
and SHA-256 hashes for every payload file. The CSV headers match the versioned contracts. The
package contains no verified status, raw HTML, evidence excerpts, cache locations, invented
values, or duplicate rows.

## Pathfinder compatibility runbook

The separate Pathfinder repository was inspected read-only and was not modified. From its
`backend` directory, first place copies of the exported files at operator-chosen paths, then run:

```powershell
python manage.py import_curated_data --template programs --file <path-to-programs.csv> --dry-run
python manage.py import_curated_data --template source_records --file <path-to-source_records.csv> --dry-run
python manage.py find_data_duplicates
python manage.py runserver
```

For an authenticated staff preview, open
`http://127.0.0.1:8000/admin/sources/data-import/`, choose the matching template, upload the
CSV, and select **Preview**. Preview and dry-run do not authorize an import; do not confirm an
import for this zero-row package.

## Lessons and next phase

The pilot improved structural coverage without weakening evidence rules, but official pages
often omit a core country label and ordinary HTTP can be refused. A useful next phase is a
small, separately authorized pilot that exercises the existing multi-source evidence behavior
on official supporting pages, with fixtures for conflicts and candidate de-duplication. Country
handling should only change through an explicit, reviewed evidence policy—not a Germany-specific
shortcut. Broader collection should wait until that policy and the handling of access-denied
sources are agreed.
