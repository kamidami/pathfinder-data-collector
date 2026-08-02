from datetime import UTC, datetime
from html import escape
from pathlib import Path
from uuid import UUID

from pathfinder_collector.config import Settings
from pathfinder_collector.persistence.models import (
    CandidateReviewModel,
    ExportCandidateModel,
    ExportRunModel,
)
from pathfinder_collector.persistence.repositories import (
    CandidateRepository,
    ExtractionEvidenceRepository,
    SourcePageRepository,
)
from pathfinder_collector.services.extraction import SUPPORTED_FIELDS


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
        source = next(
            (
                item
                for item in self.sources.list_for_job(candidate.job_id)
                if item.id == candidate.source_page_id
            ),
            None,
        )
        source_url = str(source.normalized_url).split("?", 1)[0] if source else ""
        effective_data = {**candidate.normalized_data, **candidate.reviewer_overrides}
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
            f"<td>{escape(item.evidence_locator or '')}</td>"
            f"<td>{escape(item.short_evidence_text or '')}</td>"
            "</tr>"
            for item in evidence
        )
        conflict_items = "".join(f"<li>{escape(item.field_name)}</li>" for item in conflicts)
        review_items = "".join(
            f"<li>{escape(item.reviewed_at.isoformat())}: {escape(item.decision)} by "
            f"{escape(item.reviewer_label)} → {escape(item.resulting_status)}; "
            f"fields={escape(', '.join((item.field_overrides or {}).keys()) or '-')}; "
            f"notes={escape(item.review_notes or '-')}</li>"
            for item in reviews
        )
        export_items = "".join(
            f"<li>{escape(item.created_at.isoformat())}: {escape(item.id)} "
            f"({escape(item.status)})</li>"
            for item in exports
        )
        missing_items = "".join(f"<li>{escape(item)}</li>" for item in missing)
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
Generated: {escape(generated)}<br>Source:
<a href="{escape(source_url, quote=True)}">{escape(source_url)}</a></p>
<h2>Extraction values</h2><table>{extraction_values}</table>
<h2>Effective values after reviewer overrides</h2><table>{effective_values}</table>
<h2>Missing fields</h2><ul>{missing_items}</ul>
<h2>Conflicts</h2><ul>{conflict_items}</ul>
<h2>Review history</h2><ul>{review_items}</ul>
<h2>Export history</h2><ul>{export_items}</ul>
<h2>Evidence</h2><table><tr><th>Field</th><th>Extracted</th><th>Normalized</th>
<th>Confidence</th><th>Locator</th><th>Excerpt</th></tr>{evidence_rows}</table></body></html>"""
        path = self.settings.report_dir / "candidates" / f"{candidate.id}.html"
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(document, encoding="utf-8")
        temporary.replace(path)
        return path
