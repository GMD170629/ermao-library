"""Validated, recoverable filesystem publication for directory covers."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from uuid import uuid4

from PIL import Image, UnidentifiedImageError

from app.core.exception_diagnostics import record_exception
from app.modules.library.application.source_node_commands import (
    MAX_SOURCE_NODE_COVER_BYTES,
    InvalidSourceNodeCover,
    PreparedSourceNodeCover,
    PublishedSourceNodeCover,
    SourceNodeCoverPublicationPort,
)

_IMAGE_SUFFIXES = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}


class FilesystemSourceNodeCoverPublication(SourceNodeCoverPublicationPort):
    def __init__(
        self, storage_root: Path, *, max_bytes: int = MAX_SOURCE_NODE_COVER_BYTES
    ) -> None:
        self._max_bytes = max_bytes
        self._storage_root = storage_root.resolve()
        self._cover_root = self._storage_root / "covers" / "source-nodes"

    def prepare(
        self, *, source_node_id: str, content: bytes
    ) -> PreparedSourceNodeCover:
        if not source_node_id or Path(source_node_id).name != source_node_id:
            raise InvalidSourceNodeCover("invalid source node identifier")
        if not content or len(content) > self._max_bytes:
            raise InvalidSourceNodeCover("source node cover exceeds the supported size")
        self._cover_root.mkdir(parents=True, exist_ok=True)
        temporary_path = self._cover_root / f".{source_node_id}.{uuid4().hex}.part"
        try:
            temporary_path.write_bytes(content)
        except OSError as error:
            diagnostic_id = record_exception(
                logging.getLogger(__name__), "library.source_node_cover.stage_failed", error,
                context={"step": "stage_uploaded_cover", "resource_id": source_node_id},
            )
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError as cleanup_error:
                record_exception(
                    logging.getLogger(__name__), "library.source_node_cover.cleanup_failed", cleanup_error,
                    context={"step": "remove_rejected_cover", "parent_diagnostic_id": diagnostic_id, "resource_id": source_node_id},
                )
            raise
        try:
            with Image.open(temporary_path) as image:
                image_format = str(image.format or "").upper()
                image.verify()
            suffix = _IMAGE_SUFFIXES.get(image_format)
            if suffix is None:
                raise InvalidSourceNodeCover("source node cover is not a supported image")
        except Exception as exc:
            diagnostic_id = record_exception(
                logging.getLogger(__name__), "library.source_node_cover.validation_failed", exc,
                context={"step": "validate_uploaded_cover", "resource_id": source_node_id},
            )
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError as cleanup_error:
                record_exception(
                    logging.getLogger(__name__), "library.source_node_cover.cleanup_failed", cleanup_error,
                    context={"step": "remove_rejected_cover", "parent_diagnostic_id": diagnostic_id, "resource_id": source_node_id},
                )
            if isinstance(exc, (UnidentifiedImageError, Image.DecompressionBombError, InvalidSourceNodeCover)):
                raise InvalidSourceNodeCover("source node cover could not be validated") from exc
            raise
        final_path = self._cover_root / f"{source_node_id}{suffix}"
        return PreparedSourceNodeCover(
            temporary_path=temporary_path,
            final_path=final_path,
            stored_path=final_path.relative_to(self._storage_root).as_posix(),
        )

    def publish(
        self,
        prepared: PreparedSourceNodeCover,
        *,
        previous_stored_path: str | None,
    ) -> PublishedSourceNodeCover:
        del previous_stored_path
        backup_path = None
        if prepared.final_path.exists():
            backup_path = prepared.final_path.with_name(
                f".{prepared.final_path.name}.{uuid4().hex}.backup"
            )
            os.replace(prepared.final_path, backup_path)
        try:
            os.replace(prepared.temporary_path, prepared.final_path)
        except OSError:
            if backup_path is not None and backup_path.exists():
                os.replace(backup_path, prepared.final_path)
            prepared.temporary_path.unlink(missing_ok=True)
            raise
        return PublishedSourceNodeCover(prepared=prepared, backup_path=backup_path)

    def revert(self, published: PublishedSourceNodeCover) -> None:
        published.prepared.final_path.unlink(missing_ok=True)
        if published.backup_path is not None and published.backup_path.exists():
            os.replace(published.backup_path, published.prepared.final_path)

    def complete(
        self,
        published: PublishedSourceNodeCover,
        *,
        previous_stored_path: str | None,
    ) -> None:
        if published.backup_path is not None:
            published.backup_path.unlink(missing_ok=True)
        if (
            previous_stored_path
            and previous_stored_path != published.prepared.stored_path
        ):
            self.remove(previous_stored_path)

    def discard(self, prepared: PreparedSourceNodeCover) -> None:
        prepared.temporary_path.unlink(missing_ok=True)

    def remove(self, stored_path: str) -> None:
        candidate = (self._storage_root / stored_path).resolve()
        try:
            candidate.relative_to(self._cover_root.resolve())
        except ValueError:
            # diagnostics-control-flow: Relative-path containment probe rejects an out-of-root optional cover.
            return
        candidate.unlink(missing_ok=True)


__all__ = [
    "FilesystemSourceNodeCoverPublication",
]
