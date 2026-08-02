# Programme field mapping

The deterministic extractor supports only the following initial fields.

| Collector field | Pathfinder v1 programmes column | Notes |
|---|---|---|
| `program_name` | `program_name` | Explicit heading, label, or programme JSON-LD |
| `university_name` | `university_name` | Provider, explicit label, or site-name metadata |
| `country_code` | `country_code` | Explicit country evidence only |
| `city` | `city` | Explicit programme location/campus label only |
| `degree_level` | `degree_level` | Controlled bachelor/master/phd normalization |
| `field_category` | `field_category` | Explicit subject/field label only |
| `teaching_language` | `language` | Mixed languages are preserved |
| `duration_value` + `duration_unit` | `duration` | Combined without changing original evidence |
| `intake` | `intake` | Explicit intake/start-semester label |
| `application_url` | `application_url` | Explicit labelled link only |
| `source_url` | `source_url` | Canonical URL or source-page URL |

`duration_semesters` and `study_mode` are collector-only review metadata because the v1 contract
has no exact columns for them. They remain in normalized candidate data and evidence but are not
invented as CSV columns.

Reviewer overrides take precedence only in effective approved/export values and remain stored
separately from extraction. `teaching_language` maps to `language`; duration value and unit map to
`duration`. Source retrieval/approval date maps to the contract's available date field, without
claiming official verification. `source_confidence` is `high` for the reviewed official source,
while `data_status` remains conservatively `collected`, never `verified`.

Tuition, deadlines, requirements, test scores, documents, scholarships, and unlisted fields are
unsupported in this phase and remain blank. Missing values are never guessed.
