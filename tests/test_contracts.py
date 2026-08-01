import csv
from pathlib import Path

from pathfinder_collector.config import Settings
from pathfinder_collector.contracts.pathfinder_v1 import export_model, load_manifest


def test_contract_manifest_loads() -> None:
    manifest = load_manifest()
    assert manifest.contract_version == "1"
    assert len(manifest.entities) == 6


def test_exact_csv_header_order() -> None:
    settings = Settings(_env_file=None)
    manifest = load_manifest(settings)
    for entity in manifest.entities:
        path = settings.contract_manifest_path.parent / entity.template
        with path.open(newline="", encoding="utf-8") as handle:
            assert next(csv.reader(handle)) == entity.columns
            assert list(csv.reader(handle)) == []


def test_typed_export_schema() -> None:
    model = export_model(load_manifest().entity("programs"))
    record = model(country_code="DE", program_name="Example")
    assert record.country_code == "DE"


def test_contract_does_not_depend_on_pathfinder_repository() -> None:
    source = Path(__file__).parents[1] / "src/pathfinder_collector/contracts/pathfinder_v1.py"
    assert "Desktop\\pathfinder" not in source.read_text(encoding="utf-8")
