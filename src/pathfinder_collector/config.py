from functools import lru_cache
from pathlib import Path
from typing import ClassVar

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def find_project_root() -> Path:
    for parent in (Path(__file__).resolve(), *Path(__file__).resolve().parents):
        if (parent / "pyproject.toml").is_file():
            return parent
    return Path.cwd().resolve()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PATHFINDER_COLLECTOR_", env_file=".env", extra="ignore"
    )

    project_root: Path = find_project_root()
    database_url: str = "sqlite:///var/collector.db"
    export_dir: Path = Path("var/exports")
    cache_dir: Path = Path("var/cache")
    report_dir: Path = Path("var/reports")
    log_level: str = "INFO"
    user_agent: str = "PathfinderCollector/0.2 (+public-data-research)"
    connect_timeout_seconds: float = Field(default=10, gt=0, le=120)
    read_timeout_seconds: float = Field(default=30, gt=0, le=300)
    max_response_bytes: int = Field(default=5 * 1024 * 1024, gt=0, le=20 * 1024 * 1024)
    max_redirects: int = Field(default=5, ge=0, le=10)
    min_host_delay_seconds: float = Field(default=1.0, ge=0, le=60)
    cache_ttl_hours: float = Field(default=24, gt=0, le=24 * 30)
    robots_cache_ttl_hours: float = Field(default=24, gt=0, le=24 * 30)
    allowed_content_types: str = (
        "text/html,text/plain,application/xhtml+xml,application/xml,text/xml,"
        "application/gzip,application/x-gzip"
    )
    discovery_max_pages_per_domain: int = Field(default=20, ge=1, le=200)
    discovery_max_crawl_depth: int = Field(default=2, ge=0, le=5)
    discovery_max_links: int = Field(default=1000, ge=1, le=10000)
    discovery_max_sitemaps: int = Field(default=25, ge=1, le=100)
    discovery_max_sitemap_depth: int = Field(default=2, ge=0, le=5)

    _path_fields: ClassVar[tuple[str, ...]] = ("export_dir", "cache_dir", "report_dir")

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("invalid log level")
        return normalized

    def model_post_init(self, __context: object) -> None:
        self.project_root = self.project_root.resolve()
        for field in self._path_fields:
            path = getattr(self, field)
            setattr(self, field, path if path.is_absolute() else self.project_root / path)
        if self.database_url.startswith("sqlite:///"):
            raw_path = self.database_url.removeprefix("sqlite:///")
            if raw_path != ":memory:" and not Path(raw_path).is_absolute():
                self.database_url = f"sqlite:///{(self.project_root / raw_path).as_posix()}"

    @property
    def contract_manifest_path(self) -> Path:
        return self.project_root / "contracts/pathfinder/v1/manifest.json"

    @property
    def allowed_content_type_set(self) -> frozenset[str]:
        return frozenset(item.strip().lower() for item in self.allowed_content_types.split(","))

    def ensure_runtime_directories(self) -> None:
        for path in (self.export_dir, self.cache_dir, self.report_dir):
            path.mkdir(parents=True, exist_ok=True)
        if self.database_url.startswith("sqlite:///"):
            raw_path = self.database_url.removeprefix("sqlite:///")
            if raw_path != ":memory:":
                Path(raw_path).parent.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
