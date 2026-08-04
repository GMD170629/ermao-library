"""ZIP archive adapter for volume source-file downloads."""

from __future__ import annotations

import re
import tempfile
import zipfile
from pathlib import Path

from app.core.config import Settings
from app.modules.media.application.volume_archive import (
    PreparedVolumeArchive,
    VolumeArchiveSelection,
    VolumeArchiveSourceMissingError,
)
from app.modules.media.infrastructure.http_streaming import stored_path


def _safe_name(value: str, fallback: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "_", value).strip(" ._")
    return cleaned or fallback


class ZipVolumeArchiveWriter:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def create(self, selection: VolumeArchiveSelection) -> PreparedVolumeArchive:
        with tempfile.NamedTemporaryFile(
            prefix="shuku-volumes-", suffix=".zip", delete=False
        ) as handle:
            archive_path = Path(handle.name)
        used_names: set[str] = set()
        try:
            with zipfile.ZipFile(
                archive_path,
                mode="w",
                compression=zipfile.ZIP_DEFLATED,
            ) as archive:
                for index, source in enumerate(selection.sources, start=1):
                    path = stored_path(
                        source.source_path,
                        self._settings,
                        database_backed=True,
                    )
                    if path is None or not path.is_file():
                        raise VolumeArchiveSourceMissingError("VOLUME_SOURCE_MISSING")
                    extension = path.suffix
                    base = _safe_name(source.volume_title, f"volume-{index}")
                    candidate = f"{index:03d}-{base}{extension}"
                    duplicate = 2
                    while candidate.casefold() in used_names:
                        candidate = f"{index:03d}-{base}-{duplicate}{extension}"
                        duplicate += 1
                    used_names.add(candidate.casefold())
                    archive.write(path, arcname=candidate)
            return PreparedVolumeArchive(
                path=str(archive_path),
                download_name=f"{_safe_name(selection.work_title, 'work')}-volumes.zip",
            )
        except Exception:
            archive_path.unlink(missing_ok=True)
            raise
