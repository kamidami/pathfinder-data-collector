# Germany G1 first approved export

Completion date: 2026-08-02  
Collector version: 0.1.0, base commit `7b47207`  
Pilot job: `d1c9d59d-8685-439a-802d-e3c7802865d8`

This phase re-reviewed the four existing Germany G1 candidates. Human approval means that a
reviewer accepted the evidence-backed collector record for export; it is not official university
or Pathfinder verification.

## Context and conflict workflow

The job's `DE` country code was explicitly applied to each candidate as
`operator_job_context`. The values are stored outside SourcePage evidence, remain attributable to
the job, and are disabled if official country evidence contradicts them. TUM already had official
`DE` evidence, so its effective exported country remained source-backed. Operator context supplied
the missing effective country for RWTH, Stuttgart, and Saarland. No contradiction was found.

TUM had two unresolved optional-field conflicts:

- `city`: the two official pages did not provide one unambiguous programme-city value;
- `study_mode`: the supporting evidence did not provide one supported unambiguous mode.

`pilot-reviewer` explicitly used `clear_optional_field` for both with bounded reasons. Both source
evidence records remain, the selected effective values are blank, and append-only conflict
resolution history records the decisions. No core field was cleared and no value override was
used. The one TUM extraction warning was explicitly acknowledged during approval.

## Candidate outcomes

| Programme | Before | Context contribution | Conflicts | Final status | Exported |
|---|---|---|---|---|---|
| TUM Data Engineering and Analytics | needs_review: two unresolved optional conflicts | recorded and agreeing; country remains official-source-backed | city and study_mode cleared | exported | yes |
| RWTH Data Science | needs_review: missing country_code | country_code=DE from job context | none | exported | yes |
| Stuttgart Computer Science | needs_review: missing country_code | country_code=DE from job context | none | exported | yes |
| Saarland DSAI | needs_review: missing country_code | country_code=DE from job context | none | exported | yes |
| TU Berlin Computer Science | no candidate; primary HTTP 403 | none | none | no candidate | no |

No TU Berlin retry, bypass, or synthetic candidate was attempted. No approved candidate was
skipped by export; the fifth pilot input had no candidate and therefore was not selectable.

## Blocker metrics

Before Task 0.7, zero of four candidates was approval-ready: three lacked country context and TUM
had two unresolved conflicts plus a warning requiring acknowledgement. After explicit context,
conflict decisions, report inspection, and review:

- approval-core completion: 21/30 pilot-input slots to 24/30 (the remaining six belong to the
  inaccessible TU Berlin input);
- available-candidate approval readiness: 0/4 to 4/4;
- unresolved conflicts: 2 to 0;
- optional conflicts explicitly cleared: 2;
- selected value overrides: 0;
- operator-context effective fields in export: 3;
- candidates approved/exported: 4/4 available candidates, or 4/5 pilot inputs;
- approximate additional review time: 12 minutes.

These figures describe only this controlled five-input pilot and are not representative of German
universities generally.

## Export

The duplicate check found no exact programme duplicates. Dry-run selected four approved records.
The real package is:

`var/exports/1587f844-72e7-4c02-b14f-2726a0249f39/`

It contains four `programs.csv` rows and six deduplicated official `source_records.csv` rows. The
source file contains no operator-context pseudo-source. Headers match Pathfinder v1, unsupported
values are blank, and every programme has `data_status=collected`, never `verified`.

The manifest reports:

- 30 effective fields from official source evidence;
- 3 from operator job context;
- 0 selected value fields from reviewer overrides;
- 4 human-approved candidate records.

SHA-256 hashes for `programs.csv`, `source_records.csv`, and `validation_report.txt` were verified
independently after export. The package contains no cache paths, evidence excerpts, raw HTML, or
fake source rows.

## Implementation and lessons

Migration `0006_context_conflict_resolution.py` adds separately attributed candidate context,
blocking context contradictions, and append-only conflict-resolution history. The CLI now supports
context inspection/application and explicit conflict listing/resolution. Reports distinguish
source values, context, overrides, unresolved/resolved conflicts, reviewer decisions, blockers,
and eligibility. Re-extraction retains unchanged evidence identities and manual resolutions; new
material evidence reopens the conflict without deleting the earlier audit.

For the remaining country pilots, job country may be useful because the operator deliberately
defines collection scope, but it must always remain explicit, candidate/job-bound, separately
attributed, and subordinate to contradictory official evidence. Optional uncertainty should be
left blank through an audited decision, not normalized away to improve completion. This workflow
does not establish Germany-wide or nine-country coverage.
