import os
import tempfile
from pathlib import Path

from pathfinder_collector.fetching.hashing import sha256_text


class EvidenceCache:
    def __init__(self, root: Path) -> None:
        self.root = root

    @staticmethod
    def safe_host_directory(host: str) -> str:
        return sha256_text(host)[:20]

    def page_path(self, host: str, content_hash: str, content_type: str) -> Path:
        extension = ".html" if content_type in {"text/html", "application/xhtml+xml"} else ".txt"
        return self.root / "pages" / self.safe_host_directory(host) / f"{content_hash}{extension}"

    def robots_path(self, origin: str) -> Path:
        return self.root / "robots" / f"{sha256_text(origin)}.txt"

    @staticmethod
    def atomic_write(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temp_name = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        except BaseException:
            Path(temp_name).unlink(missing_ok=True)
            raise
