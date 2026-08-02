# Human review workflow

Automatic extraction produces `collected` or `needs_review`; it can never approve a candidate.
An explicit local review records an append-only decision with a short operator label, timestamp,
bounded notes, changed fields, original status, and resulting status. Operator labels are not
accounts or email addresses, and approval is human review—not official source verification.

Approval requires programme name, university, country code, degree level, teaching language,
and a safe source URL; an intact source cache/hash and source relationship; valid controlled
values; no unresolved conflicts; and explicit acknowledgement of any non-blocking extraction
warnings. Failed review validation saves neither overrides nor history.

Overrides are accepted only from the documented programme field allowlist. They remain separate
from extracted normalized data and evidence. Required fields cannot be cleared during approval;
optional fields can be intentionally cleared with an empty string. Internal IDs, statuses,
timestamps, evidence, relationships, and arbitrary JSON cannot be overridden.

```powershell
python -m pathfinder_collector candidate review <candidate-id> --decision approve --reviewer local-1
python -m pathfinder_collector candidate history <candidate-id>
python -m pathfinder_collector candidate review-interactive <candidate-id>
```

Override files must be UTF-8 JSON objects within the project directory and no larger than 64 KiB.
Interactive approval has no default and requires final confirmation. Cancellation saves nothing.

Statuses mean:

- `collected`: all extraction core fields were found deterministically.
- `needs_review`: extraction is incomplete, weak, or conflicting.
- `approved`: a human explicitly accepted the effective values.
- `rejected`: a human rejected the candidate.
- `exported`: a human-approved candidate was included in a completed export.

Conflict resolution remains deliberately limited: unresolved extraction conflicts block approval.
Reviewers must return the candidate for correction rather than silently bypassing a conflict.

Use `candidate blockers <candidate-id>` before review for bounded categories, missing and
low-confidence core fields, conflicts, warnings, source integrity, and current export eligibility.
Candidate reports distinguish the primary and supporting sources and attribute every evidence row.

`candidate context <id> --apply-job-country` explicitly records the job's validated two-letter
country with `operator_job_context` provenance. Repeating it is idempotent. Different explicit
official country evidence disables the context and creates a blocking context conflict.

Evidence conflicts support `select-first`, `select-second`, `override`, `clear-optional`, and
`keep-unresolved`. Every action requires a reviewer and reason. Selected values are stored as
reviewer overrides without changing either evidence record. Core fields cannot be cleared;
override resolution must match retained official evidence. Unchanged re-extraction preserves a
resolution, while materially different evidence reopens a conflict and keeps the earlier audit.
