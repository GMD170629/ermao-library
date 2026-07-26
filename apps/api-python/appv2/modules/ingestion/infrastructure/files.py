from __future__ import annotations

import fnmatch
import hashlib
import html
import mimetypes
import os
import re
import shutil
import time
import uuid
import zipfile
from pathlib import Path
from typing import BinaryIO

from appv2.modules.ingestion.contracts import (
    ConversionPreparationPort,
    DirectoryNode,
    FileDiscoveryPort,
    PreparedImport,
    UploadStoragePort,
)

MAX_TEXT_CONVERSION_BYTES = 20 * 1024 * 1024

SUPPORTED_FORMATS = {
    ".epub": ("book", "epub", "application/epub+zip"),
    ".pdf": ("pdf", "pdf", "application/pdf"),
    ".cbz": ("comic", "cbz", "application/vnd.comicbook+zip"),
    ".zip": ("comic", "cbz", "application/vnd.comicbook+zip"),
    ".txt": ("text", "txt", "text/plain"),
    ".fb2": ("text", "txt", "application/x-fictionbook+xml"),
    ".mobi": ("book", "mobi", "application/x-mobipocket-ebook"),
    ".azw": ("book", "mobi", "application/vnd.amazon.ebook"),
    ".azw3": ("book", "azw3", "application/vnd.amazon.ebook"),
    ".prc": ("book", "mobi", "application/x-mobipocket-ebook"),
    ".mp3": ("audiobook", "audio", "audio/mpeg"),
    ".m4a": ("audiobook", "audio", "audio/mp4"),
    ".m4b": ("audiobook", "audio", "audio/mp4"),
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

    def validate_source(self, path: str, *, allowed_roots: tuple[str, ...]) -> str:
        candidate = Path(path).expanduser().resolve()
        roots = tuple(Path(root).expanduser().resolve() for root in allowed_roots)
        if not roots or not any(candidate.is_relative_to(root) for root in roots):
            raise ValueError("import source must remain under an authorized monitor folder")
        if not candidate.is_file():
            raise ValueError("import source does not exist")
        if candidate.suffix.casefold() not in SUPPORTED_FORMATS:
            raise ValueError("unsupported import format")
        return str(candidate)

    def discover(self, path: str, *, recursive: bool) -> list[str]:
        root = Path(self.validate_folder(path))
        iterator = root.rglob("*") if recursive else root.glob("*")
        return sorted(
            str(item.resolve())
            for item in iterator
            if item.is_file() and item.suffix.casefold() in SUPPORTED_FORMATS
        )

    def discover_stable(
        self,
        path: str,
        *,
        recursive: bool,
        stability_seconds: float,
        options: dict[str, object],
    ) -> tuple[list[str], int]:
        candidates = self.discover(path, recursive=recursive)
        root = Path(path).resolve()
        ignore_hidden = options.get("ignoreHidden", True) is not False
        configured_patterns = options.get("ignorePatterns", [])
        patterns = (
            tuple(value for value in configured_patterns if isinstance(value, str))
            if isinstance(configured_patterns, list)
            else ()
        )
        minimum_value = options.get("minFileSizeBytes", 0)
        minimum_size = minimum_value if isinstance(minimum_value, int) else 0
        configured_extensions = options.get("allowedExtensions", [])
        allowed_extensions = (
            {value.casefold() for value in configured_extensions if isinstance(value, str)}
            if isinstance(configured_extensions, list) and configured_extensions
            else set(SUPPORTED_FORMATS)
        )
        candidates = [
            candidate
            for candidate in candidates
            if Path(candidate).suffix.casefold() in allowed_extensions
            and self._eligible_candidate(
                Path(candidate),
                root=root,
                ignore_hidden=ignore_hidden,
                patterns=patterns,
                minimum_size=minimum_size,
            )
        ]
        before: dict[str, tuple[int, int]] = {}
        for candidate in candidates:
            try:
                stat = Path(candidate).stat()
            except OSError:
                continue
            before[candidate] = (stat.st_size, stat.st_mtime_ns)
        if before and stability_seconds > 0:
            time.sleep(stability_seconds)
        stable: list[str] = []
        for candidate, snapshot in before.items():
            try:
                stat = Path(candidate).stat()
            except OSError:
                continue
            if (stat.st_size, stat.st_mtime_ns) == snapshot:
                stable.append(candidate)
        return stable, len(candidates) - len(stable)

    @staticmethod
    def _eligible_candidate(
        candidate: Path,
        *,
        root: Path,
        ignore_hidden: bool,
        patterns: tuple[str, ...],
        minimum_size: int,
    ) -> bool:
        relative = candidate.relative_to(root)
        if ignore_hidden and any(part.startswith(".") for part in relative.parts):
            return False
        relative_name = relative.as_posix()
        if any(
            fnmatch.fnmatch(relative_name, pattern) or fnmatch.fnmatch(candidate.name, pattern)
            for pattern in patterns
        ):
            return False
        try:
            return candidate.stat().st_size >= minimum_size
        except OSError:
            return False

    def source_exists(self, path: str) -> bool:
        return Path(path).expanduser().is_file()

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


class LocalImportPreparation:
    def prepare(self, source_path: str) -> PreparedImport:
        path = Path(source_path).expanduser().resolve()
        if not path.is_file():
            raise ValueError("import source does not exist")
        suffix = path.suffix.casefold()
        detected = SUPPORTED_FORMATS.get(suffix)
        if detected is None:
            raise ValueError("unsupported import format")
        media_type, format_name, file_media_type = detected
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
            file_media_type=file_media_type,
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


class LocalTextToEpubConversion(ConversionPreparationPort):
    def __init__(self, conversions_root: Path) -> None:
        self._root = conversions_root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def prepare(
        self,
        source_path: str,
        *,
        identity: str,
        language: str | None,
    ) -> PreparedImport:
        source = Path(source_path).expanduser().resolve()
        if not source.is_file() or source.suffix.casefold() != ".txt":
            raise ValueError("only existing text files can be converted")
        payload = source.read_bytes()
        if len(payload) > MAX_TEXT_CONVERSION_BYTES:
            raise ValueError("text conversion source exceeds the 20 MiB limit")
        try:
            text = payload.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise ValueError("text conversion source must be UTF-8") from error
        source_checksum = hashlib.sha256(payload).hexdigest()
        output_identity = hashlib.sha256(f"{source_checksum}\0{identity}".encode()).hexdigest()
        title = re.sub(r"[_-]+", " ", source.stem).strip() or source.stem
        destination = self._root / f"{output_identity}.epub"
        if not destination.exists():
            self._write_epub(
                destination,
                title=title,
                text=text,
                identifier=f"urn:uuid:{identity}",
                language=language or "und",
            )
        output = destination.read_bytes()
        return PreparedImport(
            title=title,
            author=None,
            media_type="book",
            file_media_type="application/epub+zip",
            format="epub",
            source_path=str(destination),
            original_name=f"{source.stem}.epub",
            size_bytes=len(output),
            checksum=hashlib.sha256(output).hexdigest(),
            metadata={
                "convertedFromFormat": "txt",
                "sourceEditionId": identity,
                "sourceChecksum": source_checksum,
            },
        )

    @staticmethod
    def _write_epub(
        destination: Path,
        *,
        title: str,
        text: str,
        identifier: str,
        language: str,
    ) -> None:
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        escaped_title = html.escape(title)
        escaped_text = html.escape(text)
        try:
            with zipfile.ZipFile(temporary, "w") as archive:
                archive.writestr(
                    "mimetype",
                    "application/epub+zip",
                    compress_type=zipfile.ZIP_STORED,
                )
                archive.writestr(
                    "META-INF/container.xml",
                    '<?xml version="1.0" encoding="UTF-8"?>'
                    '<container version="1.0" '
                    'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                    '<rootfiles><rootfile full-path="OEBPS/content.opf" '
                    'media-type="application/oebps-package+xml"/></rootfiles>'
                    "</container>",
                )
                archive.writestr(
                    "OEBPS/content.opf",
                    '<?xml version="1.0" encoding="UTF-8"?>'
                    '<package xmlns="http://www.idpf.org/2007/opf" '
                    'unique-identifier="book-id" version="3.0">'
                    '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
                    f'<dc:identifier id="book-id">{html.escape(identifier)}</dc:identifier>'
                    f"<dc:title>{escaped_title}</dc:title>"
                    f"<dc:language>{html.escape(language)}</dc:language>"
                    "</metadata><manifest>"
                    '<item id="nav" href="nav.xhtml" '
                    'media-type="application/xhtml+xml" properties="nav"/>'
                    '<item id="text" href="text.xhtml" '
                    'media-type="application/xhtml+xml"/>'
                    '</manifest><spine><itemref idref="text"/></spine></package>',
                )
                archive.writestr(
                    "OEBPS/nav.xhtml",
                    '<?xml version="1.0" encoding="UTF-8"?>'
                    '<html xmlns="http://www.w3.org/1999/xhtml" '
                    'xmlns:epub="http://www.idpf.org/2007/ops"><head>'
                    f"<title>{escaped_title}</title></head><body>"
                    '<nav epub:type="toc"><ol><li><a href="text.xhtml">'
                    f"{escaped_title}</a></li></ol></nav></body></html>",
                )
                archive.writestr(
                    "OEBPS/text.xhtml",
                    '<?xml version="1.0" encoding="UTF-8"?>'
                    '<html xmlns="http://www.w3.org/1999/xhtml"><head>'
                    f"<title>{escaped_title}</title>"
                    "<style>body{line-height:1.7;margin:5%;}"
                    "pre{font-family:serif;white-space:pre-wrap;word-wrap:break-word;}"
                    "</style></head><body>"
                    f"<h1>{escaped_title}</h1><pre>{escaped_text}</pre>"
                    "</body></html>",
                )
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
