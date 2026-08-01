from pathlib import Path

from pathfinder_collector.config import Settings


def test_configuration_defaults_are_local() -> None:
    settings = Settings(_env_file=None)
    assert settings.database_url.startswith("sqlite:///")
    assert settings.export_dir.is_absolute()
    database_url_without_project = settings.database_url.lower().replace(
        "pathfinder-data-collector", ""
    )
    assert "desktop/pathfinder/" not in database_url_without_project


def test_runtime_directory_creation(temp_settings: Settings) -> None:
    temp_settings.ensure_runtime_directories()
    assert temp_settings.export_dir.is_dir()
    assert temp_settings.cache_dir.is_dir()
    assert temp_settings.report_dir.is_dir()
    database_path = Path(temp_settings.database_url.removeprefix("sqlite:///"))
    assert database_path.parent.is_dir()
