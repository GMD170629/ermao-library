from __future__ import annotations

import hashlib
import html
import io
import mimetypes
import os
import re
import subprocess
import tempfile
import zipfile
from collections.abc import Iterable
from pathlib import Path, PurePosixPath
from xml.etree.ElementTree import Element

import pypdfium2 as pdfium  # type: ignore[import-untyped]
from defusedxml import ElementTree

from appv2.modules.catalog.contracts import (
    PreparedCatalogFile,
    PreparedCatalogVolume,
    PreparedPublication,
)
from appv2.modules.ingestion.contracts import ImportPreparationPort
from appv2.modules.ingestion.infrastructure.audio_metadata import (
    AudioFileMetadata,
    parse_audio_metadata,
)

ARCHIVE_MAX_ENTRIES = 20_000
ARCHIVE_MAX_UNCOMPRESSED_BYTES = 4 * 1024 * 1024 * 1024
IMAGE_SUFFIXES = {".avif", ".bmp", ".gif", ".jpeg", ".jpg", ".png", ".webp"}
AUDIO_SUFFIXES = {".m4a", ".m4b", ".mp3"}
MOBI_SUFFIXES = {".azw", ".azw3", ".mobi", ".prc"}


class UnsafePublication(ValueError):
    pass


def _checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _natural_key(value: str) -> tuple[object, ...]:
    return tuple(
        int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", value)
    )


def _identity(
    *,
    title: str,
    author: str | None,
    identifiers: Iterable[str] = (),
) -> tuple[str, tuple[str, ...]]:
    normalized_identifiers = tuple(
        value.strip().casefold() for value in identifiers if value.strip()
    )
    source = (
        f"id:{normalized_identifiers[0]}"
        if normalized_identifiers
        else f"title:{title.strip().casefold()}\0author:{(author or '').strip().casefold()}"
    )
    return hashlib.sha256(source.encode()).hexdigest(), normalized_identifiers


def _single_file(
    path: Path,
    *,
    title: str,
    author: str | None,
    media_type: str,
    format_name: str,
    language: str | None,
    identifiers: Iterable[str],
    metadata: dict[str, object],
    file_media_type: str,
    cover: bytes | None = None,
    cover_media_type: str | None = None,
    page_count: int | None = None,
) -> PreparedPublication:
    identity_key, normalized_identifiers = _identity(
        title=title,
        author=author,
        identifiers=identifiers,
    )
    volume = PreparedCatalogVolume(
        key="main",
        title=title,
        sort_order=0,
        page_count=page_count,
    )
    return PreparedPublication(
        identity_key=identity_key,
        title=title,
        author=author,
        media_type=media_type,
        format=format_name,
        language=language,
        identifiers=normalized_identifiers,
        metadata=metadata,
        volumes=(volume,),
        files=(
            PreparedCatalogFile(
                source_path=str(path),
                original_name=path.name,
                media_type=file_media_type,
                size_bytes=path.stat().st_size,
                checksum=_checksum(path),
                volume_key=volume.key,
            ),
        ),
        cover_content=cover,
        cover_media_type=cover_media_type,
    )


def _safe_archive(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    values = archive.infolist()
    if len(values) > ARCHIVE_MAX_ENTRIES:
        raise UnsafePublication("archive has too many entries")
    if sum(item.file_size for item in values) > ARCHIVE_MAX_UNCOMPRESSED_BYTES:
        raise UnsafePublication("archive expands beyond the safety limit")
    for item in values:
        path = PurePosixPath(item.filename.replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts:
            raise UnsafePublication("archive contains an unsafe path")
        if item.external_attr >> 16 & 0o170000 == 0o120000:
            raise UnsafePublication("archive contains a symbolic link")
    return values


def _text(element: Element | None) -> str | None:
    if element is None or element.text is None:
        return None
    value = element.text.strip()
    return value or None


class LocalPublicationPreparation(ImportPreparationPort):
    def __init__(
        self,
        conversions_root: Path,
        *,
        libmobi_bin: str = "mobitool",
        conversion_timeout_seconds: int = 120,
        auto_convert_to_epub: bool = True,
    ) -> None:
        self._conversions_root = conversions_root.resolve()
        self._conversions_root.mkdir(parents=True, exist_ok=True)
        self._libmobi_bin = libmobi_bin
        self._conversion_timeout = conversion_timeout_seconds
        self._auto_convert = auto_convert_to_epub

    def prepare(
        self,
        source_path: str,
        *,
        auto_convert_to_epub: bool | None = None,
    ) -> PreparedPublication:
        path = Path(source_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(source_path)
        suffix = path.suffix.casefold()
        if suffix == ".epub":
            return self._epub(path)
        if suffix == ".pdf":
            return self._pdf(path)
        if suffix in {".cbz", ".zip"}:
            return self._comic(path)
        if suffix in {".txt", ".fb2"}:
            return self._text_publication(
                path,
                auto_convert_to_epub=(
                    self._auto_convert if auto_convert_to_epub is None else auto_convert_to_epub
                ),
            )
        if suffix in MOBI_SUFFIXES:
            return self._mobi(path)
        if suffix in AUDIO_SUFFIXES:
            return self._audio_bundle(path)
        raise ValueError(f"unsupported import format: {suffix}")

    def _epub(self, path: Path) -> PreparedPublication:
        try:
            with zipfile.ZipFile(path) as archive:
                _safe_archive(archive)
                if archive.read("mimetype") != b"application/epub+zip":
                    raise UnsafePublication("EPUB mimetype is invalid")
                container = ElementTree.fromstring(archive.read("META-INF/container.xml"))
                rootfile = container.find(".//{*}rootfile")
                if rootfile is None:
                    raise UnsafePublication("EPUB container has no package document")
                package_name = rootfile.attrib.get("full-path", "")
                package_path = PurePosixPath(package_name)
                if package_path.is_absolute() or ".." in package_path.parts:
                    raise UnsafePublication("EPUB package path is unsafe")
                package = ElementTree.fromstring(archive.read(package_name))
                title = _text(package.find(".//{*}title")) or path.stem
                author = _text(package.find(".//{*}creator"))
                language = _text(package.find(".//{*}language"))
                identifiers = [
                    value
                    for node in package.findall(".//{*}identifier")
                    if (value := _text(node)) is not None
                ]
                subjects = [
                    value
                    for node in package.findall(".//{*}subject")
                    if (value := _text(node)) is not None
                ]
                manifest = {
                    item.attrib.get("id", ""): item
                    for item in package.findall(".//{*}manifest/{*}item")
                }
                cover_item = next(
                    (
                        item
                        for item in manifest.values()
                        if "cover-image" in item.attrib.get("properties", "").split()
                    ),
                    None,
                )
                if cover_item is None:
                    cover_meta = package.find(".//{*}meta[@name='cover']")
                    if cover_meta is not None:
                        cover_item = manifest.get(cover_meta.attrib.get("content", ""))
                cover = None
                cover_media_type = None
                if cover_item is not None:
                    cover_name = str(package_path.parent / cover_item.attrib.get("href", ""))
                    cover = archive.read(cover_name)
                    cover_media_type = cover_item.attrib.get("media-type")
                spine_count = len(package.findall(".//{*}spine/{*}itemref"))
        except (KeyError, OSError, zipfile.BadZipFile, ElementTree.ParseError) as error:
            raise UnsafePublication("EPUB structure is invalid") from error
        return _single_file(
            path,
            title=title,
            author=author,
            media_type="book",
            format_name="epub",
            language=language,
            identifiers=identifiers,
            metadata={
                "subjects": subjects,
                "readingUnitCount": spine_count,
                "sourceFormat": "epub",
            },
            file_media_type="application/epub+zip",
            cover=cover,
            cover_media_type=cover_media_type,
        )

    def _pdf(self, path: Path) -> PreparedPublication:
        try:
            document = pdfium.PdfDocument(str(path))
            page_count = len(document)
            raw_metadata = document.get_metadata_dict()
            metadata = {
                str(key): str(value) for key, value in raw_metadata.items() if value is not None
            }
            title = metadata.get("Title") or path.stem
            author = metadata.get("Author") or None
            cover = None
            if page_count:
                image = document[0].render(scale=1).to_pil()
                output = io.BytesIO()
                image.thumbnail((1200, 1800))
                image.save(output, format="PNG")
                cover = output.getvalue()
        except Exception as error:
            raise UnsafePublication("PDF structure is invalid") from error
        finally:
            if "document" in locals():
                document.close()
        return _single_file(
            path,
            title=title,
            author=author,
            media_type="pdf",
            format_name="pdf",
            language=None,
            identifiers=(),
            metadata={"pdf": metadata, "pageCount": page_count},
            file_media_type="application/pdf",
            cover=cover,
            cover_media_type="image/png" if cover else None,
            page_count=page_count,
        )

    def _comic(self, path: Path) -> PreparedPublication:
        try:
            with zipfile.ZipFile(path) as archive:
                entries = _safe_archive(archive)
                pages = sorted(
                    (
                        item
                        for item in entries
                        if PurePosixPath(item.filename).suffix.casefold() in IMAGE_SUFFIXES
                    ),
                    key=lambda item: _natural_key(item.filename),
                )
                if not pages:
                    raise UnsafePublication("comic archive contains no images")
                info_entry = next(
                    (
                        item
                        for item in entries
                        if PurePosixPath(item.filename).name.casefold() == "comicinfo.xml"
                    ),
                    None,
                )
                info = (
                    ElementTree.fromstring(archive.read(info_entry))
                    if info_entry is not None
                    else None
                )
                title = (
                    (_text(info.find("Series")) if info is not None else None)
                    or (_text(info.find("Title")) if info is not None else None)
                    or path.stem
                )
                author = _text(info.find("Writer")) if info is not None else None
                language = _text(info.find("LanguageISO")) if info is not None else None
                volume_number = _text(info.find("Volume")) if info is not None else None
                cover_index = 0
                if info is not None:
                    cover_node = info.find(".//Page[@Type='FrontCover']")
                    if cover_node is not None:
                        cover_index = int(cover_node.attrib.get("Image", "0"))
                cover_entry = pages[min(max(cover_index, 0), len(pages) - 1)]
                cover = archive.read(cover_entry)
        except (
            OSError,
            ValueError,
            zipfile.BadZipFile,
            ElementTree.ParseError,
        ) as error:
            raise UnsafePublication("comic archive is invalid") from error
        identity_key, identifiers = _identity(title=title, author=author)
        volume = PreparedCatalogVolume(
            key=f"volume:{volume_number or '1'}",
            title=(f"{title} Vol. {volume_number}" if volume_number is not None else title),
            sort_order=max(int(volume_number or "1") - 1, 0),
            page_count=len(pages),
        )
        return PreparedPublication(
            identity_key=identity_key,
            title=title,
            author=author,
            media_type="comic",
            format="cbz",
            language=language,
            identifiers=identifiers,
            metadata={
                "pageCount": len(pages),
                "pageEntries": [item.filename for item in pages],
                "sourceFormat": path.suffix.casefold().lstrip("."),
            },
            volumes=(volume,),
            files=(
                PreparedCatalogFile(
                    source_path=str(path),
                    original_name=path.name,
                    media_type="application/vnd.comicbook+zip",
                    size_bytes=path.stat().st_size,
                    checksum=_checksum(path),
                    volume_key=volume.key,
                ),
            ),
            cover_content=cover,
            cover_media_type=mimetypes.guess_type(cover_entry.filename)[0],
        )

    def _text_publication(
        self,
        path: Path,
        *,
        auto_convert_to_epub: bool,
    ) -> PreparedPublication:
        if path.suffix.casefold() == ".fb2":
            try:
                root = ElementTree.fromstring(path.read_bytes())
            except ElementTree.ParseError as error:
                raise UnsafePublication("FB2 structure is invalid") from error
            title = _text(root.find(".//{*}book-title")) or path.stem
            first = _text(root.find(".//{*}first-name"))
            last = _text(root.find(".//{*}last-name"))
            author = " ".join(value for value in (first, last) if value) or None
            language = _text(root.find(".//{*}lang"))
            paragraphs = [
                value
                for node in root.findall(".//{*}body//{*}p")
                if (value := _text(node)) is not None
            ]
            text = "\n\n".join(paragraphs)
            chapter_count = len(root.findall(".//{*}body//{*}section"))
        else:
            payload = path.read_bytes()
            text = self._decode_text(payload)
            title = path.stem
            author = None
            language = None
            chapter_count = len(
                re.findall(
                    r"^\s*(?:第.{1,12}[章节回卷]|chapter\s+\d+)",
                    text,
                    flags=re.IGNORECASE | re.MULTILINE,
                )
            )
        if not text.strip():
            raise UnsafePublication("text publication has no readable content")
        if not auto_convert_to_epub:
            return _single_file(
                path,
                title=title,
                author=author,
                media_type="text",
                format_name="txt",
                language=language,
                identifiers=(),
                metadata={
                    "sourceFormat": path.suffix.casefold().lstrip("."),
                    "chapterCount": chapter_count,
                },
                file_media_type="text/plain",
            )
        converted = self._write_text_epub(path, title, text, language or "und")
        publication = self._epub(converted)
        return PreparedPublication(
            identity_key=_identity(title=title, author=author)[0],
            title=title,
            author=author,
            media_type="book",
            format="epub",
            language=language,
            identifiers=publication.identifiers,
            metadata={
                **publication.metadata,
                "convertedFromFormat": path.suffix.casefold().lstrip("."),
                "sourcePath": str(path),
                "sourceChecksum": _checksum(path),
                "chapterCount": chapter_count,
            },
            volumes=publication.volumes,
            files=publication.files
            + (
                PreparedCatalogFile(
                    source_path=str(path),
                    original_name=path.name,
                    media_type=(
                        "application/x-fictionbook+xml"
                        if path.suffix.casefold() == ".fb2"
                        else "text/plain"
                    ),
                    size_bytes=path.stat().st_size,
                    checksum=_checksum(path),
                    sort_order=1,
                    volume_key="main",
                    metadata={"role": "conversionSource"},
                ),
            ),
            cover_content=publication.cover_content,
            cover_media_type=publication.cover_media_type,
        )

    def _mobi(self, path: Path) -> PreparedPublication:
        checksum = _checksum(path)
        destination = self._conversions_root / f"{checksum}.epub"
        if not destination.exists():
            with tempfile.TemporaryDirectory(
                prefix="mobi-", dir=self._conversions_root
            ) as directory:
                # The executable is deployment configuration and every argument is
                # passed as a separate argv element; no shell parsing is involved.
                result = subprocess.run(  # noqa: S603
                    [self._libmobi_bin, "-e", "-o", directory, str(path)],
                    capture_output=True,
                    text=True,
                    timeout=self._conversion_timeout,
                    check=False,
                )
                candidates = sorted(Path(directory).glob("*.epub"))
                if result.returncode != 0 or not candidates:
                    detail = (result.stderr or result.stdout).casefold()
                    if "drm" in detail or "encrypted" in detail:
                        raise ValueError("DRM_PROTECTED")
                    raise RuntimeError("libmobi conversion failed")
                os.replace(candidates[0], destination)
        publication = self._epub(destination)
        return PreparedPublication(
            identity_key=publication.identity_key,
            title=publication.title,
            author=publication.author,
            media_type=publication.media_type,
            format=publication.format,
            language=publication.language,
            identifiers=publication.identifiers,
            metadata={
                **publication.metadata,
                "convertedFromFormat": path.suffix.casefold().lstrip("."),
                "sourcePath": str(path),
                "sourceChecksum": checksum,
                "converter": "libmobi",
            },
            volumes=publication.volumes,
            files=publication.files
            + (
                PreparedCatalogFile(
                    source_path=str(path),
                    original_name=path.name,
                    media_type=mimetypes.guess_type(path.name)[0]
                    or "application/x-mobipocket-ebook",
                    size_bytes=path.stat().st_size,
                    checksum=checksum,
                    sort_order=1,
                    volume_key="main",
                    metadata={"role": "conversionSource"},
                ),
            ),
            cover_content=publication.cover_content,
            cover_media_type=publication.cover_media_type,
        )

    def _audio_bundle(self, path: Path) -> PreparedPublication:
        members = sorted(
            (
                item.resolve()
                for item in path.parent.iterdir()
                if item.is_file() and item.suffix.casefold() in AUDIO_SUFFIXES
            ),
            key=lambda item: _natural_key(item.name),
        )
        if not members:
            raise UnsafePublication("audio bundle contains no supported tracks")
        tracks: list[AudioFileMetadata] = []
        for member in members:
            try:
                tracks.append(parse_audio_metadata(member))
            except ValueError as error:
                raise UnsafePublication(str(error)) from error
        files: list[PreparedCatalogFile] = []
        total_duration = 0
        album: str | None = None
        track_title: str | None = None
        author: str | None = None
        narrator: str | None = None
        cover: bytes | None = None
        cover_media_type: str | None = None
        encoding_repairs: list[dict[str, object]] = []
        for index, track in enumerate(tracks):
            total_duration += track.duration_ms
            album = album or track.album
            track_title = track_title or track.title
            author = author or track.author
            narrator = narrator or track.narrator
            if cover is None and track.cover_data:
                cover = track.cover_data
                cover_media_type = (
                    "image/png" if track.cover_extension == ".png" else "image/jpeg"
                )
            if isinstance(track.raw_tags, dict):
                mutagen_raw = track.raw_tags.get("mutagen")
                if isinstance(mutagen_raw, dict):
                    repairs = mutagen_raw.get("encodingRepairs")
                    if isinstance(repairs, list):
                        encoding_repairs.extend(
                            {"track": track.path.name, **item}
                            for item in repairs
                            if isinstance(item, dict)
                        )
                nested_repairs = track.raw_tags.get("encodingRepairs")
                if isinstance(nested_repairs, list):
                    encoding_repairs.extend(
                        {"track": track.path.name, **item}
                        for item in nested_repairs
                        if isinstance(item, dict)
                    )
            files.append(
                PreparedCatalogFile(
                    source_path=str(track.path),
                    original_name=track.path.name,
                    media_type=mimetypes.guess_type(track.path.name)[0] or "audio/mpeg",
                    size_bytes=track.path.stat().st_size,
                    checksum=_checksum(track.path),
                    sort_order=index,
                    volume_key="main",
                    duration_ms=track.duration_ms,
                    metadata={
                        "codec": track.codec,
                        "title": track.title,
                        "album": track.album,
                        "author": track.author,
                        "narrator": track.narrator,
                        "discNumber": track.disc_number,
                        "trackNumber": track.track_number,
                        "bitrate": track.bitrate,
                        "sampleRate": track.sample_rate,
                        "channels": track.channels,
                        "chapters": [
                            {
                                "title": chapter.title,
                                "startMs": chapter.start_ms,
                                "endMs": chapter.end_ms,
                            }
                            for chapter in track.chapters
                        ],
                    },
                )
            )
        # Match v1 identity selection: prefer album/book title over track title.
        tagged_title = album or track_title
        bundle_title = path.parent.name or tagged_title or path.stem
        if len(members) == 1 and tagged_title:
            bundle_title = tagged_title
        sibling_bundles = sorted(
            (
                directory
                for directory in path.parent.parent.iterdir()
                if directory.is_dir()
                and any(
                    child.is_file() and child.suffix.casefold() in AUDIO_SUFFIXES
                    for child in directory.iterdir()
                )
            ),
            key=lambda item: _natural_key(item.name),
        )
        if len(sibling_bundles) > 1:
            title = path.parent.parent.name
            volume_order = sibling_bundles.index(path.parent)
        else:
            title = tagged_title or bundle_title
            volume_order = 0
        identity_key, identifiers = _identity(title=title, author=author)
        volume_key = hashlib.sha256(str(path.parent).encode()).hexdigest()
        publication_metadata: dict[str, object] = {
            "trackCount": len(files),
            "durationMs": total_duration,
            "bundlePath": str(path.parent),
        }
        if narrator:
            publication_metadata["narrator"] = narrator
        if encoding_repairs:
            publication_metadata["encodingRepairs"] = encoding_repairs
        # #region agent log
        try:
            import json as _json
            import urllib.request as _urlreq

            _payload = _json.dumps(
                {
                    "sessionId": "de8447",
                    "runId": "post-fix",
                    "hypothesisId": "H1",
                    "location": "formats.py:_audio_bundle",
                    "message": "audio bundle prepared with v1 metadata port",
                    "data": {
                        "source": path.name,
                        "title": title,
                        "album": album,
                        "trackTitle": track_title,
                        "author": author,
                        "narrator": narrator,
                        "chapterCount": sum(len(track.chapters) for track in tracks),
                        "encodingRepairCount": len(encoding_repairs),
                        "encodingRepairs": [
                            {
                                "tag": item.get("tag"),
                                "declaredEncoding": item.get("declaredEncoding"),
                                "detectedEncoding": item.get("detectedEncoding"),
                                "repaired": item.get("repaired"),
                            }
                            for item in encoding_repairs[:8]
                        ],
                        "codecs": [track.codec for track in tracks],
                    },
                    "timestamp": int(__import__("time").time() * 1000),
                }
            ).encode()
            _req = _urlreq.Request(
                "http://127.0.0.1:7277/ingest/37cbb0f6-b560-4540-a58d-0c1c4c637b9c",
                data=_payload,
                headers={
                    "Content-Type": "application/json",
                    "X-Debug-Session-Id": "de8447",
                },
                method="POST",
            )
            _urlreq.urlopen(_req, timeout=1).read()
        except Exception:
            pass
        # #endregion
        return PreparedPublication(
            identity_key=identity_key,
            title=title,
            author=author,
            media_type="audiobook",
            format="audio",
            language=None,
            identifiers=identifiers,
            metadata=publication_metadata,
            volumes=(
                PreparedCatalogVolume(
                    key=volume_key,
                    title=bundle_title,
                    sort_order=volume_order,
                    duration_ms=total_duration,
                ),
            ),
            files=tuple(
                PreparedCatalogFile(
                    source_path=item.source_path,
                    original_name=item.original_name,
                    media_type=item.media_type,
                    size_bytes=item.size_bytes,
                    checksum=item.checksum,
                    sort_order=item.sort_order,
                    volume_key=volume_key,
                    duration_ms=item.duration_ms,
                    metadata=item.metadata,
                )
                for item in files
            ),
            cover_content=cover,
            cover_media_type=cover_media_type,
        )

    def _write_text_epub(
        self,
        source: Path,
        title: str,
        text: str,
        language: str,
    ) -> Path:
        identity = hashlib.sha256(source.read_bytes()).hexdigest()
        destination = self._conversions_root / f"{identity}.epub"
        if destination.exists():
            return destination
        temporary = destination.with_suffix(".tmp")
        with zipfile.ZipFile(temporary, "w") as archive:
            archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
            archive.writestr(
                "META-INF/container.xml",
                '<?xml version="1.0"?><container version="1.0" '
                'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                '<rootfiles><rootfile full-path="OEBPS/content.opf" '
                'media-type="application/oebps-package+xml"/></rootfiles></container>',
            )
            archive.writestr(
                "OEBPS/content.opf",
                '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
                'unique-identifier="id"><metadata '
                'xmlns:dc="http://purl.org/dc/elements/1.1/">'
                f'<dc:identifier id="id">urn:sha256:{identity}</dc:identifier>'
                f"<dc:title>{html.escape(title)}</dc:title>"
                f"<dc:language>{html.escape(language)}</dc:language>"
                '</metadata><manifest><item id="text" href="text.xhtml" '
                'media-type="application/xhtml+xml"/></manifest>'
                '<spine><itemref idref="text"/></spine></package>',
            )
            archive.writestr(
                "OEBPS/text.xhtml",
                '<html xmlns="http://www.w3.org/1999/xhtml"><head>'
                f"<title>{html.escape(title)}</title></head><body><pre>"
                f"{html.escape(text)}</pre></body></html>",
            )
        os.replace(temporary, destination)
        return destination

    @staticmethod
    def _decode_text(payload: bytes) -> str:
        for encoding in ("utf-8-sig", "gb18030", "big5"):
            try:
                return payload.decode(encoding)
            except UnicodeDecodeError:
                continue
        raise UnsafePublication("text encoding is not supported")
