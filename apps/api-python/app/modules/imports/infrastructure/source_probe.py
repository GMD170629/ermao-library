"""Local filesystem adapter for import source existence checks."""

from pathlib import Path


class LocalImportSourceProbe:
    def exists(self, path: Path) -> bool:
        return path.exists()
