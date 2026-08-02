import ast
import csv
from pathlib import Path

from pathfinder_collector.contracts.pathfinder_v1 import ContractManifest


def check_pathfinder_compatibility(root: Path, manifest: ContractManifest) -> list[str]:
    """Compare the local contract with a Pathfinder checkout without importing it."""
    errors: list[str] = []
    templates = root / "backend" / "data_templates"
    for entity in (manifest.entity("programs"), manifest.entity("source_records")):
        path = templates / entity.source_pathfinder_template
        try:
            with path.open(newline="", encoding="utf-8-sig") as handle:
                actual = next(csv.reader(handle))
        except (OSError, StopIteration) as exc:
            errors.append(f"cannot read {path}: {exc}")
            continue
        if actual != entity.columns:
            errors.append(f"header drift: {entity.entity_type}")

    importer = root / "backend" / "apps" / "sources" / "services" / "curated_data_importer.py"
    models = root / "backend" / "apps" / "sources" / "models.py"
    seed = root / "backend" / "apps" / "countries" / "management" / "commands" / "seed_demo_data.py"
    try:
        importer_text = importer.read_text(encoding="utf-8")
        model_text = models.read_text(encoding="utf-8")
        seed_text = seed.read_text(encoding="utf-8")
        ast.parse(importer_text)
        ast.parse(model_text)
        ast.parse(seed_text)
    except (OSError, SyntaxError) as exc:
        errors.append(f"cannot inspect Pathfinder importer semantics: {exc}")
        return errors

    programs = manifest.entity("programs")
    sources = manifest.entity("source_records")
    checks = {
        "program required fields": all(
            repr(value) in importer_text or f'"{value}"' in importer_text
            for value in programs.required_columns
        ),
        "conditional verification date": "last_verified_date" in importer_text
        and "REAL_DATA_STATUSES" in importer_text,
        "programme statuses": all(
            value in importer_text for value in programs.allowed_values["data_status"]
        ),
        "source types": all(value in model_text for value in sources.allowed_values["source_type"]),
        "field categories": all(
            value in seed_text for value in programs.allowed_values["field_category"]
        ),
    }
    errors.extend(f"semantic drift: {name}" for name, valid in checks.items() if not valid)
    return errors
