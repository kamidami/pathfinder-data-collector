# Germany G1 approval-blocking gap analysis

Audit date: 2026-08-02  
Collector version: 0.1.0, base commit `7b47207`  
Pilot job: `d1c9d59d-8685-439a-802d-e3c7802865d8`

This follow-up used the existing five-input pilot records. It is a bounded gap analysis, not a
statistically representative assessment of Germany. Collector approval is human acceptance for
CSV export and is not official verification by a university or Pathfinder.

## Stored blocker audit before supporting collection

The matrix was derived from SourcePage, CandidateRecord, evidence, conflict, warning, cache-hash,
review-history, and contract-mapping state after migration 0005. No row relied on the earlier
pilot narrative.

| Programme | Primary state | Candidate / status | Missing approval core | Low-confidence core | Conflicts / warnings | Integrity / contract | Category | Minimum supporting source | Required action |
|---|---|---|---|---|---|---|---|---|---|
| TUM Data Engineering and Analytics | allowed; HTTP 200; fetched | `a05822e0-640b-4320-8ebe-166c801f59fd`; needs_review | teaching_language | none | none / none | intact / none | `missing_teaching_language` | official programme faculty page with an explicit instruction-language label | new evidence plus generic inline-label parsing |
| RWTH Data Science | allowed; HTTP 200; fetched | `05988dca-547a-4afc-a15e-650ab4f601e2`; needs_review | country_code | none | none / none | intact / none | `missing_country_code` | official programme/faculty page with explicit structured or labelled country | new evidence only; never infer from `.de` |
| Stuttgart Computer Science | allowed; HTTP 200; fetched | `bc296a85-8736-4bdc-821d-6ccaf5f1e140`; needs_review | country_code | none | none / none | intact / none | `missing_country_code` | official programme/faculty page with explicit structured or labelled country | new evidence; generic title normalization if equivalent headings differ |
| TU Berlin Computer Science | allowed; HTTP 403 | no candidate | not applicable | not applicable | not applicable | no cache / not applicable | `source_inaccessible` | none unless a separately allowed official programme page is identified | no action; do not bypass |
| Saarland DSAI | allowed; HTTP 200; fetched | `0786b2c5-0ab0-4759-862e-7a5819322a85`; needs_review | country_code | none | none / none | intact / none | `missing_country_code` | official university programme listing with explicit structured or labelled country | new evidence only; never infer from `.de` |

There were no invalid URLs, source-hash failures, unsupported contract values, low-confidence core
fields, or pre-existing conflicts. Reviewer overrides were neither necessary nor justified.

## Supporting pages attempted

Pages were requested individually through the safe collector. No links were crawled and no page
was force-refreshed.

| Candidate | Reason | Supporting URL | Robots | Fetch/result | Attached |
|---|---|---|---|---|---|
| TUM | explicit teaching-language evidence | https://www.cit.tum.de/en/cit/studies/degree-programs/master-data-engineering-and-analytics/ | allowed | HTTP 200, fetched | yes, supporting SourcePage `c8f93d0a-157e-440b-b265-74eec48fcaeb` |
| RWTH | explicit country evidence | https://sc.informatik.rwth-aachen.de/de/studium/master/master-data-science/ | unavailable | page request stopped | no |
| Stuttgart | explicit country evidence | https://www.f05.uni-stuttgart.de/en/cs/prospective-students/msc-computerscience/ | allowed | HTTP 200, fetched | yes, supporting SourcePage `17773ebc-a33a-4d1b-9dc3-5f244195eb3f` |
| Saarland | explicit country evidence | https://www.uni-saarland.de/en/future/your-path/english-taught-master-programmes.html | allowed | network failure after bounded retries | no |

TU Berlin was not retried and no alternate page was fetched. The TUM supporting page completed
`teaching_language=English` through explicit labelled evidence. It also produced meaningful,
equally strong city and study-mode disagreements with the primary source; these remain unresolved.
The Stuttgart page agreed on programme identity, degree, and institution but did not explicitly
state a country. RWTH and Saarland supplied no content because their safe fetches did not succeed.

## Generic implementation

- Migration `0005_candidate_sources.py` adds the minimal candidate/source association and
  backfills every existing primary source.
- Supporting extraction requires `--candidate`; it attaches to the existing candidate, retains
  the primary source, replaces evidence only for the selected source, and is idempotent.
- Aggregate resolution retains evidence from every source, treats agreement as agreement, creates
  conflicts for equally strong disagreements, and retains the primary canonical source URL.
- Two independent agreeing medium-confidence official sources deterministically yield high
  agreement confidence. Confidence remains evidence strength, not verification.
- Generic inline `<strong>Label</strong>: value` extraction now captures the TUM language pattern.
- Controlled programme-title normalization removes a leading or trailing degree token, allowing
  `M.Sc. Computer Science` and `Computer Science` to agree without fixed programme knowledge.
- Candidate blocker output reports missing core fields, weak evidence, conflicts, warnings,
  source integrity, eligibility, and controlled blocker categories without page text or paths.
- Candidate reports now distinguish primary/supporting URLs, attribute each evidence row, show
  agreement/conflict state, blockers, review notes, effective values, and export eligibility.
- Approved multi-source exports emit deduplicated source rows for every attached official source.

Minimal synthetic fixtures cover both real structural defects and cross-source agreement and
disagreement. No downloaded page, domain mapping, fixed pilot value, source-specific adapter, AI,
discovery, browser automation, or Pathfinder access was added.

## Re-review result

| Programme | Newly completed fields | Overrides | Final blockers | Final status | Export eligible | Additional review |
|---|---|---:|---|---|---|---:|
| TUM | teaching_language | 0 | unresolved city and study_mode conflicts; non-blocking warning acknowledged | needs_review | no | ~5 min |
| RWTH | none | 0 | missing_country_code | needs_review | no | ~2 min |
| Stuttgart | equivalent programme titles now agree; no approval core field added | 0 | missing_country_code | needs_review | no | ~4 min |
| TU Berlin | none | 0 | source_inaccessible | no candidate | no | ~1 min |
| Saarland | none | 0 | missing_country_code | needs_review | no | ~2 min |

All decisions were recorded by `pilot-reviewer`; no candidate was approved merely to create an
output row. The duplicate check found no exact programme duplicates. The requested
`germany-g1-core-completed` dry-run selected zero approved candidates and safely reported four
skips. Per the task rule, no real export was run because no candidate was genuinely approved;
there is therefore no new export package.

## Before-and-after metrics

| Metric | Before | After |
|---|---:|---:|
| Primary pages attempted / fetched | 5 / 4 | unchanged |
| Supporting pages attempted / fetched | 0 / 0 | 4 / 2 |
| Candidates created | 4 | 4 (no duplicates) |
| Fully complete extraction-core candidates | 3/5 (60.0%) | 4/5 (80.0%) |
| Extraction-core slots supported | 19/25 (76.0%) | 20/25 (80.0%) |
| Approval-core slots supported | 20/30 (66.7%) | 21/30 (70.0%) |
| Overall effective supported fields | 31/70 (44.3%) | 30/70 (42.9%) |
| Low-confidence core-field rate | 0/5 (0.0%) | 0/5 (0.0%) |
| Candidate conflict rate | 0/5 (0.0%) | 1/5 (20.0%) |
| Reviewer override rate | 0/5 (0.0%) | 0/5 (0.0%) |
| Approval / export rate | 0/5 / 0/5 | 0/5 / 0/5 |
| Approximate review time | 15 minutes | 14 additional; 29 cumulative |

The supported-field total fell by one because aggregate conflict handling correctly omitted two
disputed optional TUM values while adding one supported teaching-language value. This is safer
than silently preserving a primary value and is not a regression in trust behavior.

## Lessons and remaining limitations

For later country pilots, explicit country evidence should be considered during manual source
selection; official programme pages commonly assume location context. A reviewed evidence policy
may allow a programme-specific page to be paired with a tightly bounded official institutional
identity/address record, but that policy must be designed before collection and must not become a
domain-to-country shortcut. Supporting hosts can have independent robots or availability outcomes,
and a second source can reveal legitimate differences rather than merely fill gaps.

The collector still does not resolve conflicts automatically, infer institution country, render
JavaScript-only pages, bypass denied sources, or claim broad German—much less nine-country—coverage.
Human approval remains distinct from official verification.
