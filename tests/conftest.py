import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pathfinder_collector.cli import app
from pathfinder_collector.config import Settings, get_settings


@pytest.fixture
def temp_settings(tmp_path: Path) -> Settings:
    contract_source = Path(__file__).parents[1] / "contracts/pathfinder/v1"
    shutil.copytree(contract_source, tmp_path / "contracts/pathfinder/v1")
    settings = Settings(
        project_root=tmp_path,
        database_url="sqlite:///var/test.db",
        export_dir="var/exports",
        cache_dir="var/cache",
        report_dir="var/reports",
        min_host_delay_seconds=0,
        _env_file=None,
    )
    settings.ensure_runtime_directories()
    return settings


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def cli_with_settings(temp_settings: Settings, monkeypatch: pytest.MonkeyPatch):
    source_manifest = Path(__file__).parents[1] / "contracts/pathfinder/v1/manifest.json"
    destination = temp_settings.contract_manifest_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(source_manifest.read_text(encoding="utf-8"), encoding="utf-8")
    get_settings.cache_clear()
    monkeypatch.setattr("pathfinder_collector.cli.settings", lambda: temp_settings)
    return app
