import csv
import io
import json
import re
import shutil
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from pathfinder_collector import __version__
from pathfinder_collector.config import Settings
from pathfinder_collector.contracts.pathfinder_v1 import load_manifest
from pathfinder_collector.enums import CandidateStatus, EntityType, ExportStatus, ResolutionStatus
from pathfinder_collector.fetching.hashing import sha256_bytes
from pathfinder_collector.persistence.models import (
    CandidateContextModel,
    CandidateModel,
    CandidateSourceModel,
    ConflictModel,
    ContextConflictModel,
    ExportCandidateModel,
    ExportFileModel,
    ExportRunModel,
    SourcePageModel,
)
from pathfinder_collector.services.extraction import SUPPORTED_FIELDS
from pathfinder_collector.services.review import (
    APPROVAL_CORE_FIELDS,
    ReviewValidationError,
    effective_candidate_data,
    validate_effective_programme,
)


class ExportResult(BaseModel):
    export_run_id: UUID = Field(default_factory=uuid4)
    approved_selected: int = 0
    exported_count: int = 0
    skipped_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    duplicate_groups: list[list[UUID]] = Field(default_factory=list)
    export_directory: Path | None = None
    file_hashes: dict[str, str] = Field(default_factory=dict)
    dry_run: bool = False


class PathfinderExportService:
    def __init__(self, settings: Settings, session: Session) -> None:
        self.settings = settings
        self.session = session
        self.manifest = load_manifest(settings)

    def export_programs(
        self,
        *,
        candidate_ids: list[UUID] | None = None,
        job_id: UUID | None = None,
        output_name: str | None = None,
        dry_run: bool = False,
    ) -> ExportResult:
        if candidate_ids is None and job_id is None:
            raise ValueError("provide a job or at least one candidate")
        output_name = _output_name(output_name)
        result = ExportResult(dry_run=dry_run)
        candidates = self._select(candidate_ids, job_id)
        approved: list[CandidateModel] = []
        for candidate in candidates:
            if candidate.entity_type != EntityType.PROGRAM.value or candidate.review_status not in {
                CandidateStatus.APPROVED.value,
                CandidateStatus.EXPORTED.value,
            }:
                result.skipped_count += 1
                result.warnings.append(f"Candidate {candidate.id} skipped: not approved")
                continue
            error = self._blocking_error(candidate)
            if error:
                result.errors.append(f"Candidate {candidate.id}: {error}")
                continue
            approved.append(candidate)
        result.approved_selected = len(approved)
        duplicate_groups = duplicate_candidate_groups(approved, self.session)
        result.duplicate_groups = [[UUID(item.id) for item in group] for group in duplicate_groups]
        if duplicate_groups:
            result.errors.append("Exact duplicate programme candidates cannot be exported together")
        if result.errors:
            return result
        program_rows: list[dict[str, str]] = []
        source_rows: list[dict[str, str]] = []
        for candidate in approved:
            try:
                program_rows.append(self._program_row(candidate))
                source_rows.extend(self._source_rows(candidate))
            except ValueError as exc:
                result.errors.append(f"Candidate {candidate.id}: {exc}")
        if result.errors:
            return result
        source_rows = _deduplicate_rows(source_rows)
        program_header = self.manifest.entity("programs").columns
        source_header = self.manifest.entity("source_records").columns
        _validate_rows(self.manifest.entity("programs"), program_rows)
        _validate_rows(self.manifest.entity("source_records"), source_rows)
        if dry_run:
            result.exported_count = len(approved)
            return result

        run_id = result.export_run_id
        final_directory = self.settings.export_dir / str(run_id)
        temporary = self.settings.export_dir / f".tmp-{run_id}"
        if final_directory.exists() or temporary.exists():
            raise ValueError("export run directory already exists")
        temporary.mkdir(parents=True)
        try:
            program_bytes = _csv_bytes(program_header, program_rows)
            source_bytes = _csv_bytes(source_header, source_rows)
            report_text = _validation_report(len(approved), result)
            files = {
                "programs.csv": program_bytes,
                "source_records.csv": source_bytes,
                "validation_report.txt": report_text.encode("utf-8"),
            }
            for filename, content in files.items():
                (temporary / filename).write_bytes(content)
            hashes = {filename: sha256_bytes(content) for filename, content in files.items()}
            generated_at = datetime.now(UTC)
            manifest = {
                "collector_version": __version__,
                "pathfinder_contract_version": self.manifest.contract_version,
                "export_run_id": str(run_id),
                "output_name": output_name,
                "generated_at": generated_at.isoformat(),
                "candidate_count": len(approved),
                "candidate_ids": [candidate.id for candidate in approved],
                "files": hashes,
                "review_status_summary": {"human_approved": len(approved)},
                "warnings_count": len(result.warnings),
                "field_provenance_counts": self._provenance_counts(approved),
            }
            manifest_bytes = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8") + b"\n"
            (temporary / "manifest.json").write_bytes(manifest_bytes)
            hashes["manifest.json"] = sha256_bytes(manifest_bytes)
            temporary.replace(final_directory)
            try:
                run_model = ExportRunModel(
                    id=str(run_id),
                    entity_type=EntityType.PROGRAM.value,
                    schema_version="pathfinder-v1",
                    record_count=len(approved),
                    export_path=str(final_directory.relative_to(self.settings.project_root)),
                    status=ExportStatus.COMPLETED.value,
                    created_at=generated_at,
                    completed_at=generated_at,
                )
                self.session.add(run_model)
                self.session.flush()
                for filename, digest in hashes.items():
                    self.session.add(
                        ExportFileModel(
                            export_run_id=str(run_id),
                            filename=filename,
                            sha256=digest,
                            record_count=(
                                len(program_rows)
                                if filename == "programs.csv"
                                else len(source_rows)
                                if filename == "source_records.csv"
                                else 0
                            ),
                        )
                    )
                for candidate in approved:
                    self.session.add(
                        ExportCandidateModel(export_run_id=str(run_id), candidate_id=candidate.id)
                    )
                    candidate.review_status = CandidateStatus.EXPORTED.value
                self.session.commit()
            except Exception:
                self.session.rollback()
                shutil.rmtree(final_directory, ignore_errors=True)
                raise
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        result.export_directory = final_directory
        result.exported_count = len(approved)
        result.file_hashes = hashes
        return result

    def show(self, run_id: UUID) -> tuple[ExportRunModel, list[ExportFileModel]]:
        run = self.session.get(ExportRunModel, str(run_id))
        if run is None:
            raise ValueError("export run does not exist")
        files = self.session.scalars(
            select(ExportFileModel).where(ExportFileModel.export_run_id == str(run_id))
        ).all()
        return run, list(files)

    def _select(
        self, candidate_ids: list[UUID] | None, job_id: UUID | None
    ) -> list[CandidateModel]:
        statement = select(CandidateModel).order_by(CandidateModel.id)
        if candidate_ids is not None:
            statement = statement.where(
                CandidateModel.id.in_([str(candidate_id) for candidate_id in candidate_ids])
            )
        if job_id is not None:
            statement = statement.where(CandidateModel.job_id == str(job_id))
        return list(self.session.scalars(statement).all())

    def _blocking_error(self, candidate: CandidateModel) -> str | None:
        unresolved = self.session.scalar(
            select(ConflictModel.id).where(
                ConflictModel.candidate_id == candidate.id,
                ConflictModel.resolution_status == ResolutionStatus.UNRESOLVED.value,
            )
        )
        if unresolved:
            return "unresolved conflict"
        context_unresolved = self.session.scalar(
            select(ContextConflictModel.id).where(
                ContextConflictModel.candidate_id == candidate.id,
                ContextConflictModel.resolution_status == ResolutionStatus.UNRESOLVED.value,
            )
        )
        if context_unresolved:
            return "operator context contradicts official source evidence"
        data = effective_candidate_data(candidate, self.session)
        if not data.get("field_category", "").strip():
            return "missing required fields: field_category"
        missing = [field for field in APPROVAL_CORE_FIELDS if not data.get(field, "").strip()]
        if missing:
            return f"missing required fields: {', '.join(sorted(missing))}"
        try:
            validate_effective_programme(data)
        except ReviewValidationError as exc:
            return str(exc)
        if (
            not candidate.source_page_id
            or self.session.get(SourcePageModel, candidate.source_page_id) is None
        ):
            return "missing source relationship"
        return None

    def _program_row(self, candidate: CandidateModel) -> dict[str, str]:
        data = effective_candidate_data(candidate, self.session)
        row = {column: "" for column in self.manifest.entity("programs").columns}
        direct = {
            "country_code",
            "university_name",
            "program_name",
            "degree_level",
            "field_category",
            "city",
            "intake",
            "application_url",
            "source_url",
        }
        for field in direct:
            row[field] = data.get(field, "")
        row["country_code"] = _mapped_value(
            self.manifest.entity("programs"), "country_code", row["country_code"]
        )
        row["language"] = data.get("teaching_language", "")
        if data.get("duration_value") and data.get("duration_unit"):
            row["duration"] = f"{data['duration_value']} {data['duration_unit']}"
        row["source_confidence"] = "high"
        row["data_status"] = "collected"
        row["last_verified_date"] = (
            candidate.approved_at.date().isoformat() if candidate.approved_at else ""
        )
        return {key: formula_safe(value) for key, value in row.items()}

    def _source_rows(self, candidate: CandidateModel) -> list[dict[str, str]]:
        data = effective_candidate_data(candidate, self.session)
        sources = self.session.scalars(
            select(SourcePageModel)
            .join(CandidateSourceModel, CandidateSourceModel.source_page_id == SourcePageModel.id)
            .where(CandidateSourceModel.candidate_id == candidate.id)
            .order_by(CandidateSourceModel.created_at)
        ).all()
        rows: list[dict[str, str]] = []
        for source in sources:
            row = {column: "" for column in self.manifest.entity("source_records").columns}
            row.update(
                {
                    "title": data.get("program_name", ""),
                    "source_type": _mapped_value(
                        self.manifest.entity("source_records"), "source_type", source.source_type
                    ),
                    "url": _without_query(source.normalized_url),
                    "publisher": data.get("university_name", ""),
                    "country_code": _mapped_value(
                        self.manifest.entity("source_records"),
                        "country_code",
                        data.get("country_code", ""),
                    ),
                    "related_entity_type": "program",
                    "related_entity_name": data.get("program_name", ""),
                    "last_verified_date": candidate.approved_at.date().isoformat()
                    if candidate.approved_at
                    else "",
                    "confidence": "high",
                    "notes": "Human-reviewed collector record; not official verification.",
                }
            )
            rows.append({key: formula_safe(value) for key, value in row.items()})
        return rows

    def _provenance_counts(self, candidates: list[CandidateModel]) -> dict[str, int]:
        counts = {
            "official_source_evidence": 0,
            "reviewer_overrides": 0,
            "operator_job_context": 0,
        }
        for candidate in candidates:
            effective = effective_candidate_data(candidate, self.session)
            context_fields = set(
                self.session.scalars(
                    select(CandidateContextModel.field_name).where(
                        CandidateContextModel.candidate_id == candidate.id,
                        CandidateContextModel.effective.is_(True),
                    )
                ).all()
            )
            for field in SUPPORTED_FIELDS:
                if not effective.get(field, "").strip():
                    continue
                if field in (candidate.reviewer_overrides or {}):
                    counts["reviewer_overrides"] += 1
                elif field in (candidate.normalized_data or {}):
                    counts["official_source_evidence"] += 1
                elif field in context_fields:
                    counts["operator_job_context"] += 1
        return counts


def duplicate_candidate_groups(
    candidates: list[CandidateModel], session: Session | None = None
) -> list[list[CandidateModel]]:
    groups: dict[tuple[str, str, str, str], list[CandidateModel]] = {}
    for candidate in candidates:
        data = effective_candidate_data(candidate, session)
        key = tuple(
            " ".join(data.get(field, "").casefold().split())
            for field in ("country_code", "university_name", "program_name", "degree_level")
        )
        groups.setdefault(key, []).append(candidate)
    return [group for key, group in groups.items() if all(key) and len(group) > 1]


def formula_safe(value: object) -> str:
    text = "" if value is None else str(value)
    if text.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + text
    return text


def _csv_bytes(header: list[str], rows: list[dict[str, str]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=header, extrasaction="raise", lineterminator="\r\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def _validate_rows(entity: object, rows: list[dict[str, str]]) -> None:
    header = entity.columns
    seen: set[tuple[str, ...]] = set()
    for row in rows:
        if list(row) != header:
            raise ValueError("contract row columns do not match exact header order")
        values = tuple(row[column] for column in header)
        if values in seen:
            raise ValueError("duplicate contract row")
        seen.add(values)
        for value in values:
            value.encode("utf-8")
        missing = [column for column in entity.required_columns if not row[column].strip()]
        missing += [
            column
            for column in entity.conditional_required.get(row.get("data_status", ""), [])
            if not row[column].strip()
        ]
        if missing:
            raise ValueError(f"{entity.entity_type} missing required values: {', '.join(missing)}")
        for column, allowed in entity.allowed_values.items():
            if row[column] and row[column] not in allowed:
                raise ValueError(
                    f"{entity.entity_type}.{column} has unsupported value: {row[column]}"
                )
        for column in entity.date_columns:
            if row[column]:
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", row[column]):
                    raise ValueError(f"{entity.entity_type}.{column} must use YYYY-MM-DD")
                date.fromisoformat(row[column])
        for column in entity.url_columns:
            if row[column] and not re.match(r"^https?://[^/\s]+", row[column]):
                raise ValueError(f"{entity.entity_type}.{column} must be an HTTP(S) URL")


def _mapped_value(entity: object, field: str, value: str) -> str:
    mapping = entity.value_mappings.get(field, {})
    if not value or not mapping:
        return value
    try:
        return mapping[value]
    except KeyError as exc:
        raise ValueError(f"no Pathfinder v1 mapping for {field} value: {value}") from exc


def _deduplicate_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    found: set[tuple[str, ...]] = set()
    result: list[dict[str, str]] = []
    for row in rows:
        key = tuple(row.values())
        if key not in found:
            found.add(key)
            result.append(row)
    return result


def _validation_report(count: int, result: ExportResult) -> str:
    return (
        f"Valid records: {count}\nSkipped records: {result.skipped_count}\n"
        f"Blocking errors: {len(result.errors)}\nWarnings: {len(result.warnings)}\n"
        "Duplicate groups: 0\nContract: Pathfinder v1\n"
        "Status: human-reviewed collection; not official verification.\n"
    )


def _without_query(url: str) -> str:
    return url.split("?", 1)[0]


def _output_name(value: str | None) -> str | None:
    if value is None:
        return None
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", value):
        raise ValueError("export name must be a short safe label")
    return value
