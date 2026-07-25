from __future__ import annotations

import hashlib
import mimetypes
import os
import re
import shutil
import uuid
from pathlib import Path
from typing import BinaryIO

from appv2.modules.ingestion.contracts import (
    DirectoryNode,
    FileDiscoveryPort,
    ImportPreparationPort,
    PreparedImport,
    UploadStoragePort,
)

SUPPORTED_FORMATS = {
    ".epub": ("book", "epub"),
    ".pdf": ("pdf", "pdf"),
    ".cbz": ("comic", "cbz"),
    ".cbr": ("comic", "cbr"),
    ".txt": ("text", "txt"),
    ".mobi": ("book", "mobi"),
    ".azw3": ("book", "azw3"),
    ".mp3": ("audiobook", "audio"),
    ".m4a": ("audiobook", "audio"),
    ".m4b": ("audiobook", "audio"),
    ".flac": ("audiobook", "audio"),
    ".ogg": ("audiobook", "audio"),
    ".wav": ("audiobook", "audio"),
}


class MonitorFileDiscovery(FileDiscoveryPort):
    def __init__(self, monitor_root: Path | None) -> None:
        self._root = monitor_root.expanduser().resolve() if monitor_root else None

    def validate_folder(self, path: str) -> str:
        candidate = Path(path).expanduser().resolve()
        if self._root is None or not candidate.is_relative_to(self._root):
            raise ValueError("monitor folder must remain under MONITOR_ROOT")
        if not candidate.is_dir():
            raise ValueError("monitor folder does not exist")
        return str(candidate)

    def discover(self, path: str, *, recursive: bool) -> list[str]:
        root = Path(self.validate_folder(path))
        iterator = root.rglob("*") if recursive else root.glob("*")
        return sorted(
            str(item.resolve())
            for item in iterator
            if item.is_file() and item.suffix.casefold() in SUPPORTED_FORMATS
        )

    def tree(self, path: str | None = None) -> tuple[DirectoryNode, str]:
        if self._root is None:
            raise ValueError("MONITOR_ROOT is not configured")
        candidate = Path(path).expanduser().resolve() if path else self._root
        if not candidate.is_relative_to(self._root):
            raise ValueError("directory must remain under MONITOR_ROOT")
        if not candidate.is_dir():
            raise ValueError("directory does not exist")
        children: list[DirectoryNode] = []
        try:
            directories = sorted(
                (item for item in candidate.iterdir() if item.is_dir()),
                key=lambda item: item.name.casefold(),
            )
        except OSError as error:
            return (
                DirectoryNode(
                    name=candidate.name or str(candidate),
                    path=str(candidate),
                    readable=False,
                    error=str(error),
                ),
                str(self._root),
            )
        for directory in directories:
            readable = os.access(directory, os.R_OK | os.X_OK)
            children.append(
                DirectoryNode(
                    name=directory.name,
                    path=str(directory.resolve()),
                    readable=readable,
                )
            )
        return (
            DirectoryNode(
                name=candidate.name or str(candidate),
                path=str(candidate),
                readable=True,
                children=tuple(children),
            ),
            str(self._root),
        )


class V2UploadStorage(UploadStoragePort):
    def __init__(self, temp_root: Path) -> None:
        self._root = temp_root / "uploads"

    def store(self, name: str, stream: BinaryIO) -> str:
        self._root.mkdir(parents=True, exist_ok=True)
        safe_name = re.sub(r"[^A-Za-z0-9._ -]", "_", Path(name).name)
        destination = self._root / f"{uuid.uuid4().hex}-{safe_name}"
        with destination.open("xb") as target:
            shutil.copyfileobj(stream, target, length=1024 * 1024)
        return str(destination.resolve())


class LocalImportPreparation(ImportPreparationPort):
    def prepare(self, source_path: str) -> PreparedImport:
        path = Path(source_path).expanduser().resolve()
        if not path.is_file():
            raise ValueError("import source does not exist")
        suffix = path.suffix.casefold()
        detected = SUPPORTED_FORMATS.get(suffix)
        if detected is None:
            raise ValueError("unsupported import format")
        media_type, format_name = detected
        checksum = hashlib.sha256()
        size = 0
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                checksum.update(chunk)
                size += len(chunk)
        title = re.sub(r"[_-]+", " ", path.stem).strip() or path.stem
        return PreparedImport(
            title=title,
            author=None,
            media_type=media_type,
            format=format_name,
            source_path=str(path),
            original_name=path.name,
            size_bytes=size,
            checksum=checksum.hexdigest(),
            metadata={
                "detectedMimeType": mimetypes.guess_type(path.name)[0],
                "sourceModifiedAt": path.stat().st_mtime,
                "sourceDevice": os.stat(path).st_dev,
            },
        )
