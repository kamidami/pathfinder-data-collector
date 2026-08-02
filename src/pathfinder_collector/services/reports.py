from datetime import UTC, datetime
from html import escape
from pathlib import Path
from uuid import UUID

from pathfinder_collector.config import Settings
from pathfinder_collector.persistence.models import (
    CandidateContextModel,
    CandidateModel,
    CandidateReviewModel,
    ConflictResolutionModel,
    ExportCandidateModel,
    ExportRunModel,
)
from pathfinder_collector.persistence.repositories import (
    CandidateRepository,
    ExtractionEvidenceRepository,
    SourcePageRepository,
)
from pathfinder_collector.services.blockers import CandidateBlockerService
from pathfinder_collector.services.extraction import SUPPORTED_FIELDS
from pathfinder_collector.services.review import effective_candidate_data


class CandidateReportService:
    def __init__(
        self,
        settings: Settings,
        candidates: CandidateRepository,
        evidence: ExtractionEvidenceRepository,
        sources: SourcePageRepository,
    ) -> None:
        self.settings = settings
        self.candidates = candidates
        self.evidence = evidence
        self.sources = sources

    def generate(self, candidate_id: UUID) -> Path:
        candidate = self.candidates.get(candidate_id)
        if candidate is None:
            raise ValueError("candidate does not exist")
        evidence = self.evidence.evidence_for(candidate_id)
        conflicts = self.evidence.conflicts_for(candidate_id)
        session = self.evidence.session
        reviews = (
            session.query(CandidateReviewModel)
            .filter_by(candidate_id=str(candidate_id))
            .order_by(CandidateReviewModel.reviewed_at)
            .all()
        )
        exports = (
            session.query(ExportRunModel)
            .join(ExportCandidateModel, ExportCandidateModel.export_run_id == ExportRunModel.id)
            .filter(ExportCandidateModel.candidate_id == str(candidate_id))
            .order_by(ExportRunModel.created_at)
            .all()
        )
        contexts = (
            session.query(CandidateContextModel)
            .filter_by(candidate_id=str(candidate_id))
            .order_by(CandidateContextModel.created_at)
            .all()
        )
        resolution_history = (
            session.query(ConflictResolutionModel)
            .filter_by(candidate_id=str(candidate_id))
            .order_by(ConflictResolutionModel.reviewed_at)
            .all()
        )
        candidate_sources = self.candidates.sources_for(candidate_id)
        source_by_id = {str(item.id): item for item, _role in candidate_sources}
        source_items = "".join(
            _source_list_item(item.normalized_url, role) for item, role in candidate_sources
        )
        blocker_result = CandidateBlockerService(self.candidates, self.evidence).analyze(
            candidate_id
        )
        candidate_model = session.get(CandidateModel, str(candidate_id))
        effective_data = effective_candidate_data(candidate_model, session)
        missing = sorted(SUPPORTED_FIELDS - {key for key, value in effective_data.items() if value})
        extraction_values = "".join(
            f"<tr><th>{escape(str(key))}</th><td>{escape(str(value))}</td></tr>"
            for key, value in sorted(candidate.normalized_data.items())
        )
        effective_values = "".join(
            f"<tr><th>{escape(str(key))}</th><td>{escape(str(value))}</td></tr>"
            for key, value in sorted(effective_data.items())
        )
        evidence_rows = "".join(
            "<tr>"
            f"<td>{escape(item.field_name)}</td>"
            f"<td>{escape(item.extracted_value)}</td>"
            f"<td>{escape(item.normalized_value or '')}</td>"
            f"<td>{escape(item.confidence.value)}</td>"
            f"<td>{escape(_evidence_source_url(source_by_id, item.source_page_id))}</td>"
            f"<td>{escape(item.evidence_locator or '')}</td>"
            f"<td>{escape(item.short_evidence_text or '')}</td>"
            "</tr>"
            for item in evidence
        )
        unresolved_items = "".join(
            f"<li>{escape(item.field_name)}</li>"
            for item in conflicts
            if item.resolution_status.value == "unresolved"
        )
        resolved_items = "".join(
            f"<li>{escape(item.field_name)}: "
            f"selected={escape(item.resolved_value or '(blank)')}</li>"
            for item in conflicts
            if item.resolution_status.value == "resolved"
        )
        conflict_fields = {item.field_name for item in conflicts}
        field_sources: dict[str, set[str]] = {}
        field_values: dict[str, set[str]] = {}
        for item in evidence:
            field_sources.setdefault(item.field_name, set()).add(str(item.source_page_id))
            value = item.normalized_value or item.extracted_value
            field_values.setdefault(item.field_name, set()).add(value.casefold())
        agreement_items = "".join(
            f"<li>{escape(field)}: "
            f"{escape(_agreement_state(field, sources, field_values[field], conflict_fields))}</li>"
            for field, sources in sorted(field_sources.items())
        )
        review_items = "".join(
            f"<li>{escape(item.reviewed_at.isoformat())}: {escape(item.decision)} by "
            f"{escape(item.reviewer_label)} → {escape(item.resulting_status)}; "
            f"fields={escape(', '.join((item.field_overrides or {}).keys()) or '-')}; "
            f"notes={escape(item.review_notes or '-')}</li>"
            for item in reviews
        )
        context_items = "".join(
            f"<li>{escape(item.field_name)} = {escape(item.value)}; provenance=job context; "
            f"effective={escape('yes' if item.effective else 'no')}</li>"
            for item in contexts
        )
        override_items = "".join(
            f"<li>{escape(field)} = {escape(value or '(blank)')}</li>"
            for field, value in sorted(candidate.reviewer_overrides.items())
        )
        resolution_items = "".join(
            f"<li>{escape(item.reviewed_at.isoformat())}: {escape(item.field_name)}; "
            f"{escape(item.resolution_action)} by {escape(item.reviewer_label)}; "
            f"selected={escape(item.selected_value if item.selected_value is not None else '-')}; "
            f"notes={escape(item.review_notes)}</li>"
            for item in resolution_history
        )
        export_items = "".join(
            f"<li>{escape(item.created_at.isoformat())}: {escape(item.id)} "
            f"({escape(item.status)})</li>"
            for item in exports
        )
        missing_items = "".join(f"<li>{escape(item)}</li>" for item in missing)
        blocker_items = "".join(f"<li>{escape(item)}</li>" for item in blocker_result.categories)
        generated = datetime.now(UTC).isoformat()
        document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Candidate review</title>
<style>body{{font-family:system-ui;max-width:1100px;margin:2rem auto;padding:0 1rem}}
table{{border-collapse:collapse;width:100%}}
th,td{{border:1px solid #bbb;padding:.45rem;text-align:left}}
.warning{{padding:1rem;background:#fff4ce;border:1px solid #d99b00}}</style></head>
<body><h1>Programme candidate review</h1>
<p class="warning">Human-approved values are not verified;
local review is not official source verification.</p>
<p>Candidate: {escape(str(candidate.id))}<br>Status: {escape(candidate.review_status.value)}<br>
Generated: {escape(generated)}<br>Export eligible:
{escape("yes" if blocker_result.export_eligible else "no")}</p>
<h2>Sources</h2><ul>{source_items}</ul>
<h2>Extraction values</h2><table>{extraction_values}</table>
<h2>Operator context values</h2><ul>{context_items}</ul>
<h2>Reviewer overrides</h2><ul>{override_items}</ul>
<h2>Effective values</h2><table>{effective_values}</table>
<h2>Missing fields</h2><ul>{missing_items}</ul>
<h2>Approval blockers</h2><ul>{blocker_items}</ul>
<h2>Unresolved conflicts</h2><ul>{unresolved_items}</ul>
<h2>Resolved conflicts</h2><ul>{resolved_items}</ul>
<h2>Conflict resolution history</h2><ul>{resolution_items}</ul>
<h2>Evidence agreement</h2><ul>{agreement_items}</ul>
<h2>Review history</h2><ul>{review_items}</ul>
<h2>Export history</h2><ul>{export_items}</ul>
<h2>Evidence</h2><table><tr><th>Field</th><th>Extracted</th><th>Normalized</th>
<th>Confidence</th><th>Source</th><th>Locator</th><th>Excerpt</th></tr>{evidence_rows}</table></body></html>"""
        path = self.settings.report_dir / "candidates" / f"{candidate.id}.html"
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(document, encoding="utf-8")
        temporary.replace(path)
        return path


def _evidence_source_url(source_by_id: dict[str, object], source_page_id: object) -> str:
    source = source_by_id.get(str(source_page_id))
    normalized_url = getattr(source, "normalized_url", "")
    return str(normalized_url).split("?", 1)[0]


def _source_list_item(url: object, role: str) -> str:
    safe_url = str(url).split("?", 1)[0]
    return (
        f'<li>{escape(role.title())}: <a href="{escape(safe_url, quote=True)}">'
        f"{escape(safe_url)}</a></li>"
    )


def _agreement_state(
    field: str, source_ids: set[str], values: set[str], conflict_fields: set[str]
) -> str:
    if field in conflict_fields:
        return "conflict"
    if len(source_ids) > 1 and len(values) == 1:
        return "agreement across official sources"
    return "single-source or complementary evidence"
