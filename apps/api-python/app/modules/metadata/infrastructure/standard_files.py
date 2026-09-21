"""Read standard metadata from an anchored, bounded stream, without extraction."""

import hashlib
import math
import os
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import replace
from pathlib import Path
from typing import BinaryIO
from zipfile import BadZipFile, ZipFile

from lxml import etree  # type: ignore[import-untyped]
from mutagen import MutagenError
from mutagen.flac import FLAC
from mutagen.id3 import ID3
from mutagen.mp4 import MP4
from pypdf.errors import PdfReadError

from app.contracts.publication_metadata import PublicationMetadata
from app.infrastructure.bounded_inspection import (
    InspectionLimitReached,
    LimitedReader,
    ZipInspectionReader,
)
from app.infrastructure.comic_archives import parse_comic_info
from app.infrastructure.epub_metadata import read_epub_package, read_zip_metadata
from app.infrastructure.pdf_metadata_reader import StrictMetadataPdfReader
from app.infrastructure.sidecar_paths import sidecar_opf_paths
from app.modules.metadata.application.opf import MAX_OPF_BYTES, parse_opf_metadata
from app.modules.metadata.application.standard_files import (
    MetadataFileSource,
    StandardMetadataError,
    StandardMetadataObservation,
)
from app.modules.metadata.infrastructure.archive_writeback import (
    BoundedArchiveStream,
    inspect_archive_entries,
    preview_archive_metadata,
)
from app.modules.metadata.infrastructure.audio_structure import (
    flac_structure,
    mp3_structure,
    mp4_structure,
)
from app.modules.metadata.infrastructure.audio_writeback import AUDIO_WRITABLE_FIELDS
from app.modules.metadata.infrastructure.pdf_writeback import (
    PDF_WRITABLE_FIELDS,
    inspect_pdf_write,
)
from app.modules.metadata.infrastructure.selective_comicinfo import (
    COMIC_WRITABLE_FIELDS,
    patch_comicinfo,
)
from app.modules.metadata.infrastructure.selective_opf import (
    OPF_WRITABLE_FIELDS,
    patch_opf_metadata,
)

FileOpener = Callable[[Path, str], AbstractContextManager[int]]


def file_revision(stat: os.stat_result) -> str:
    return hashlib.sha256(
        f"{stat.st_dev}:{stat.st_ino}:{stat.st_size}:{stat.st_mtime_ns}".encode()
    ).hexdigest()


def read_comic_metadata(content: bytes) -> PublicationMetadata:
    if b"<!DOCTYPE" in content.upper() or b"<!ENTITY" in content.upper():
        raise StandardMetadataError("INVALID_METADATA")
    root = etree.fromstring(
        content, parser=etree.XMLParser(resolve_entities=False, no_network=True)
    )
    if etree.QName(root).localname != "ComicInfo":
        raise StandardMetadataError("INVALID_METADATA")
    parsed = parse_comic_info(etree.tostring(root, encoding="unicode"))
    author = parsed.get("writer") or parsed.get("penciller")

    def number(name: str) -> float | None:
        try:
            value = float(root.findtext(name) or "")
            return value if math.isfinite(value) else None
        except ValueError:
            return None

    date = (
        "-".join(
            str(root.findtext(name))
            for name in ("Year", "Month", "Day")
            if root.findtext(name)
        )
        or None
    )
    return PublicationMetadata(
        title=parsed.get("title"),
        authors=(author,) if author else (),
        description=parsed.get("summary"),
        publisher=parsed.get("publisher"),
        subjects=tuple(parsed.get("tags") or ()),
        series_name=parsed.get("series"),
        volume_index=parsed.get("volume"),
        series_index=number("Number"),
        language=root.findtext("LanguageISO"),
        isbn=root.findtext("GTIN"),
        published_at=date,
    )


def _text(values: object) -> str | None:
    if hasattr(values, "text"):
        values = values.text
    if isinstance(values, (tuple, list)):
        return " / ".join(str(value) for value in values) or None
    return str(values) if values is not None else None


def _audio_metadata(stream: BinaryIO, extension: str) -> PublicationMetadata:
    # Standard tags only. No frame decoding, external media probes or transcoding.
    if extension == ".mp3":
        tags: dict[str, object] = dict(ID3(stream))
        names = {
            "title": "TIT2",
            "author": "TPE1",
            "description": "COMM::eng",
            "subjects": "TCON",
            "publisher": "TPUB",
            "language": "TLAN",
            "date": "TDRC",
        }
    elif extension == ".flac":
        tags = dict(FLAC(stream))
        names = {
            "title": "title",
            "author": "artist",
            "description": "description",
            "subjects": "genre",
            "publisher": "publisher",
            "language": "language",
            "date": "date",
        }
    else:
        tags = dict(MP4(stream).tags or {})
        names = {
            "title": "©nam",
            "author": "©ART",
            "description": "desc",
            "subjects": "©gen",
            "date": "©day",
        }
    values = {field: _text(tags.get(key)) for field, key in names.items()}
    author = values.get("author")
    subjects = values.get("subjects")
    return PublicationMetadata(
        title=values.get("title"),
        authors=(author,) if author else (),
        description=values.get("description"),
        subjects=(subjects,) if subjects else (),
        publisher=values.get("publisher"),
        language=values.get("language"),
        published_at=values.get("date"),
    )


class AnchoredStandardMetadataReader:
    def __init__(self, open_file: FileOpener) -> None:
        self._open = open_file

    def read(
        self,
        root: Path,
        relative_path: str,
        *,
        directory: bool,
        source: MetadataFileSource,
        sidecar_relative_path: str | None = None,
    ) -> StandardMetadataObservation:
        if source not in {"embedded", "sidecar"}:
            raise StandardMetadataError("INVALID_METADATA_SOURCE")
        if source == "embedded":
            if directory or sidecar_relative_path is not None:
                raise StandardMetadataError("EMBEDDED_FILE_REQUIRED")
            try:
                return self._read_one(root, relative_path, source)
            except FileNotFoundError as error:
                raise StandardMetadataError("SOURCE_NOT_FOUND") from error
        path = Path(relative_path)
        candidates = tuple(
            dict.fromkeys(
                str(candidate)
                for candidate in sidecar_opf_paths(path, directory=directory)
            )
        )
        if directory:
            candidates += (str(path / "ComicInfo.xml"),)
        if sidecar_relative_path is not None:
            if sidecar_relative_path not in candidates:
                raise StandardMetadataError("INVALID_SIDECAR_TARGET")
            candidates = (sidecar_relative_path,)
        found: list[StandardMetadataObservation] = []
        for candidate in candidates:
            try:
                found.append(self._read_one(root, candidate, source))
            except FileNotFoundError:
                continue
        if not found:
            raise StandardMetadataError("METADATA_NOT_FOUND")
        if len(found) != 1:
            raise StandardMetadataError("AMBIGUOUS_SIDECAR")
        return found[0]

    def _read_one(
        self, root: Path, relative_path: str, source: MetadataFileSource
    ) -> StandardMetadataObservation:
        writable: tuple[str, ...] = ()
        suffix = Path(relative_path).suffix.lower()
        with self._open(root, relative_path) as descriptor:
            before = os.fstat(descriptor)
            try:
                reader = (
                    ZipInspectionReader
                    if suffix in {".epub", ".cbz", ".zip"}
                    else LimitedReader
                )
                with reader(os.dup(descriptor)) as stream:
                    if suffix in {".opf", ".xml"}:
                        if before.st_size > MAX_OPF_BYTES:
                            raise StandardMetadataError("METADATA_TOO_LARGE")
                        content = stream.read(before.st_size)
                        metadata = (
                            parse_opf_metadata(content)
                            if suffix == ".opf"
                            else read_comic_metadata(content)
                        )
                        format_name = "OPF" if suffix == ".opf" else "ComicInfo"
                        try:
                            if suffix == ".opf":
                                patch_opf_metadata(
                                    content, metadata, frozenset({"title"})
                                )
                                writable = tuple(sorted(OPF_WRITABLE_FIELDS))
                            else:
                                patch_comicinfo(content, metadata, frozenset({"title"}))
                                writable = tuple(sorted(COMIC_WRITABLE_FIELDS))
                        except StandardMetadataError:
                            writable = ()
                    elif suffix in {".epub", ".cbz", ".zip"}:
                        with ZipFile(BoundedArchiveStream(stream)) as archive:
                            if suffix == ".epub":
                                _name, content = read_epub_package(archive)
                                metadata = parse_opf_metadata(content)
                                format_name = "EPUB"
                            else:
                                entries = [
                                    item.filename
                                    for item in archive.infolist()
                                    if item.filename.casefold() == "comicinfo.xml"
                                ]
                                if len(entries) != 1:
                                    raise StandardMetadataError("METADATA_NOT_FOUND")
                                metadata = read_comic_metadata(
                                    read_zip_metadata(archive, entries[0])
                                )
                                format_name = "ComicInfo"
                            try:
                                inspect_archive_entries(archive)
                                preview_archive_metadata(
                                    archive,
                                    "EPUB" if suffix == ".epub" else "CBZ",
                                    metadata,
                                    frozenset({"title"}),
                                )
                                writable = tuple(
                                    sorted(
                                        OPF_WRITABLE_FIELDS
                                        if suffix == ".epub"
                                        else COMIC_WRITABLE_FIELDS
                                    )
                                )
                            except StandardMetadataError:
                                writable = ()
                    elif suffix == ".pdf":
                        pdf = StrictMetadataPdfReader(
                            stream, strict=True, root_object_recovery_limit=0
                        )
                        if pdf.is_encrypted:
                            raise StandardMetadataError("ENCRYPTED_FILE")
                        info = pdf.metadata
                        metadata = PublicationMetadata(
                            title=str(info.title) if info and info.title else None,
                            authors=(str(info.author),) if info and info.author else (),
                            description=str(info.subject)
                            if info and info.subject
                            else None,
                        )
                        format_name = "PDF"
                        try:
                            inspect_pdf_write(stream, metadata, frozenset({"title"}))
                            writable = tuple(sorted(PDF_WRITABLE_FIELDS))
                        except (
                            StandardMetadataError,
                            InspectionLimitReached,
                            PdfReadError,
                        ):
                            writable = ()
                    elif suffix in {".mp3", ".m4a", ".m4b", ".flac"}:
                        metadata = _audio_metadata(stream, suffix)
                        format_name = {".mp3": "ID3", ".flac": "FLAC"}.get(
                            suffix, "MP4"
                        )
                        try:
                            if suffix == ".mp3":
                                mp3_structure(stream, frozenset(), verify_payload=False)
                            elif suffix == ".flac":
                                flac_structure(stream, verify_payload=False)
                            else:
                                mp4_structure(stream, verify_payload=False)
                            writable = tuple(sorted(AUDIO_WRITABLE_FIELDS))
                        except (StandardMetadataError, InspectionLimitReached):
                            writable = ()
                    else:
                        raise StandardMetadataError("UNSUPPORTED_FORMAT")
            except StandardMetadataError:
                raise
            except (
                MutagenError,
                BadZipFile,
                KeyError,
                ValueError,
                etree.XMLSyntaxError,
                PdfReadError,
            ) as error:
                raise StandardMetadataError("INVALID_METADATA") from error
            if file_revision(os.fstat(descriptor)) != file_revision(before):
                raise StandardMetadataError("SOURCE_CHANGED")
        # Covers and unparsed extension blobs are not exposed by this read API.
        metadata = replace(metadata, cover_href=None, unparsed_values=())
        return StandardMetadataObservation(
            source,
            relative_path,
            format_name,
            file_revision(before),
            metadata,
            writable,
        )
