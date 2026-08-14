"""Filesystem adapter for publication source byte identities."""

from __future__ import annotations

from pathlib import Path

from app.modules.publications.application.ports import PublicationSource
from app.modules.publications.domain.model import PublicationCorruptError
from app.modules.publications.infrastructure.source_files import (
    publication_sha256,
    resolve_publication_source,
)


class LocalPublicationSourceHasher:
    def __init__(self, storage_root: Path) -> None:
        self._storage_root = storage_root

    def sha256(self, source: PublicationSource) -> str:
        path = resolve_publication_source(source.path, self._storage_root)
        try:
            before = path.stat()
        except OSError as error:
            raise PublicationCorruptError(
                "publication source cannot be inspected"
            ) from error
        digest = publication_sha256(path)
        try:
            after = path.stat()
        except OSError as error:
            raise PublicationCorruptError(
                "publication source changed while its hash was calculated"
            ) from error
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise PublicationCorruptError(
                "publication source changed while its hash was calculated"
            )
        return f"sha256:{digest}"


__all__ = ["LocalPublicationSourceHasher"]
