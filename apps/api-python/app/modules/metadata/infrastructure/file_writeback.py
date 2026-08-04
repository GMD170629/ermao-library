"""Format-aware preparation and atomic publication of metadata file updates."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import zipfile
from base64 import b64encode
from dataclasses import dataclass, replace
from pathlib import Path

# lxml is validated at this adapter boundary and lacks PEP 561 metadata.
from lxml import etree  # type: ignore[import-untyped]

from app.contracts.publication_metadata import PublicationMetadata
from app.modules.metadata.public import (
    OpfMetadataError,
    parse_opf_metadata,
    serialize_opf_metadata,
)

DIRECT_WRITE_SUFFIXES = {".epub", ".pdf", ".cbz", ".zip", ".fb2"}
SIDECAR_SUFFIXES = {".cbr", ".rar", ".mobi", ".azw", ".azw3", ".prc", ".txt"}


class MetadataWritebackError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PreparedWriteback:
    prepared_path: Path
    output_path: Path
    output_hash: str
    written_fields: tuple[str, ...]
    warning_code: str | None = None


def _publication(
    payload: dict[str, object], storage_root: Path
) -> tuple[PublicationMetadata, Path | None]:
    authors = payload.get("authors")
    subjects = payload.get("subjects")
    cover_value = str(payload.get("coverPath") or "").strip()
    cover_path = None
    if cover_value:
        candidate = Path(cover_value)
        candidate = candidate if candidate.is_absolute() else storage_root / candidate
        try:
            resolved = candidate.resolve()
            resolved.relative_to(storage_root.resolve())
        except (OSError, ValueError):
            resolved = None
        if resolved is not None and resolved.is_file() and not resolved.is_symlink():
            cover_path = resolved
    metadata = PublicationMetadata(
        title=str(payload.get("title") or "").strip() or None,
        volume_title=str(payload.get("volumeTitle") or "").strip() or None,
        authors=tuple(str(item).strip() for item in authors if str(item).strip())
        if isinstance(authors, list)
        else (),
        description=str(payload.get("description") or "").strip() or None,
        subjects=tuple(str(item).strip() for item in subjects if str(item).strip())
        if isinstance(subjects, list)
        else (),
        series_name=str(payload.get("seriesName") or "").strip() or None,
        series_index=float(str(payload["seriesIndex"]))
        if payload.get("seriesIndex") is not None
        else None,
        volume_index=float(str(payload["volumeIndex"]))
        if payload.get("volumeIndex") is not None
        else None,
        language=str(payload.get("language") or "").strip() or None,
        publisher=str(payload.get("publisher") or "").strip() or None,
        published_at=str(payload.get("publishedAt") or "").strip() or None,
        identifier=str(payload.get("identifier") or "").strip() or None,
        isbn=str(payload.get("isbn") or "").strip() or None,
    )
    return metadata, cover_path


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _temporary(output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, value = tempfile.mkstemp(
        prefix=f".{output_path.name}.shuku-", suffix=".part", dir=output_path.parent
    )
    os.close(descriptor)
    return Path(value)


def _validate_source(source: Path, payload: dict[str, object]) -> None:
    if source.is_symlink() or not source.exists():
        raise MetadataWritebackError("源文件不存在或是符号链接")
    if source.is_dir():
        return
    stat = source.stat()
    expected_size = payload.get("sourceSize")
    expected_mtime = payload.get("sourceMtimeMs")
    if expected_size is not None and int(str(expected_size)) != stat.st_size:
        raise MetadataWritebackError("源文件已在识别后发生变化")
    if (
        expected_mtime is not None
        and abs(int(str(expected_mtime)) - int(stat.st_mtime * 1000)) > 1
    ):
        raise MetadataWritebackError("源文件已在识别后发生变化")


def _sidecar_output(source: Path) -> Path:
    return source / "metadata.opf" if source.is_dir() else source.with_suffix(".opf")


def _sidecar_cover(
    metadata: PublicationMetadata, cover: Path | None, output: Path
) -> PublicationMetadata:
    if cover is None:
        return metadata
    suffix = cover.suffix.lower() if cover.suffix else ".jpg"
    target = output.with_name(f"{output.stem}.cover{suffix}")
    temporary = _temporary(target)
    try:
        shutil.copyfile(cover, temporary)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return replace(metadata, cover_href=target.name)


def _write_sidecar(
    source: Path, metadata: PublicationMetadata, cover: Path | None
) -> tuple[Path, Path]:
    output = _sidecar_output(source)
    metadata = _sidecar_cover(metadata, cover, output)
    temporary = _temporary(output)
    content: bytes | None = None
    if output.is_file() and not output.is_symlink():
        try:
            existing_content = output.read_bytes()
            existing = parse_opf_metadata(existing_content)
            package = etree.fromstring(
                existing_content,
                etree.XMLParser(
                    resolve_entities=False,
                    no_network=True,
                    recover=False,
                    huge_tree=False,
                ),
            )
            merged = _overlay_metadata(existing, metadata)
            _replace_package_metadata(package, merged)
            if merged.cover_href:
                _set_cover_manifest(package, merged.cover_href)
            content = etree.tostring(package, xml_declaration=True, encoding="utf-8")
        except (OSError, OpfMetadataError, etree.XMLSyntaxError):
            content = None
    temporary.write_bytes(content or serialize_opf_metadata(metadata))
    return temporary, output


def _metadata_element(metadata: PublicationMetadata) -> etree._Element:
    document = etree.fromstring(serialize_opf_metadata(metadata))
    return next(node for node in document if etree.QName(node).localname == "metadata")


def _overlay_metadata(
    existing: PublicationMetadata, desired: PublicationMetadata
) -> PublicationMetadata:
    return PublicationMetadata(
        title=desired.title or existing.title,
        volume_title=desired.volume_title or existing.volume_title,
        authors=desired.authors or existing.authors,
        description=desired.description or existing.description,
        subjects=desired.subjects or existing.subjects,
        series_name=desired.series_name or existing.series_name,
        series_index=(
            desired.series_index
            if desired.series_index is not None
            else existing.series_index
        ),
        volume_index=(
            desired.volume_index
            if desired.volume_index is not None
            else existing.volume_index
        ),
        language=desired.language or existing.language,
        publisher=desired.publisher or existing.publisher,
        published_at=desired.published_at or existing.published_at,
        identifier=desired.identifier or existing.identifier,
        isbn=desired.isbn or existing.isbn,
        cover_href=desired.cover_href or existing.cover_href,
    )


def _replace_package_metadata(
    package: etree._Element, metadata: PublicationMetadata
) -> None:
    package_metadata = next(
        (node for node in package if etree.QName(node).localname == "metadata"), None
    )
    if package_metadata is None and etree.QName(package).localname == "metadata":
        package_metadata = package
    if package_metadata is None:
        raise MetadataWritebackError("EPUB OPF 缺少 metadata")
    managed = {
        "title",
        "creator",
        "description",
        "subject",
        "language",
        "publisher",
        "date",
        "identifier",
    }
    managed_meta = {
        "calibre:series",
        "calibre:series_index",
        "belongs-to-collection",
        "group-position",
        "cover",
    }
    for child in list(package_metadata):
        local = etree.QName(child).localname
        name = str(child.get("name") or child.get("property") or "").casefold()
        if local in managed or (local == "meta" and name in managed_meta):
            package_metadata.remove(child)
    replacement = _metadata_element(metadata)
    for child in replacement:
        package_metadata.append(child)


def _set_cover_manifest(package: etree._Element, href: str) -> None:
    if etree.QName(package).localname != "package":
        return
    manifest = next(
        (node for node in package if etree.QName(node).localname == "manifest"), None
    )
    if manifest is None:
        manifest = etree.SubElement(package, "manifest")
    cover_item = next(
        (
            node
            for node in manifest
            if etree.QName(node).localname == "item"
            and (
                "cover-image" in str(node.get("properties") or "").split()
                or node.get("id") == "cover-image"
            )
        ),
        None,
    )
    if cover_item is None:
        cover_item = etree.SubElement(manifest, "item")
        cover_item.set("id", "cover-image")
    cover_item.set("href", href)
    cover_item.set("media-type", "image/jpeg")
    cover_item.set("properties", "cover-image")


def _write_epub(
    source: Path, metadata: PublicationMetadata, cover: Path | None
) -> Path:
    temporary = _temporary(source)
    with zipfile.ZipFile(source, "r") as original:
        try:
            container = etree.fromstring(original.read("META-INF/container.xml"))
            rootfile = next(
                node
                for node in container.iter()
                if etree.QName(node).localname == "rootfile"
            )
            opf_path = str(rootfile.get("full-path") or "")
            package = etree.fromstring(original.read(opf_path))
        except (KeyError, StopIteration, etree.XMLSyntaxError) as exc:
            raise MetadataWritebackError("EPUB 缺少有效 OPF") from exc
        cover_archive_name = None
        if cover is not None:
            cover_archive_name = f"{Path(opf_path).parent.as_posix().rstrip('/')}/shuku-cover{cover.suffix.lower() or '.jpg'}".lstrip(
                "/"
            )
            metadata = replace(metadata, cover_href=Path(cover_archive_name).name)
        try:
            existing_metadata = parse_opf_metadata(original.read(opf_path))
            metadata = _overlay_metadata(existing_metadata, metadata)
        except OpfMetadataError:
            pass
        _replace_package_metadata(package, metadata)
        if metadata.cover_href:
            _set_cover_manifest(package, metadata.cover_href)
        replacements = {
            opf_path: etree.tostring(package, xml_declaration=True, encoding="utf-8")
        }
        with zipfile.ZipFile(temporary, "w") as output:
            for info in original.infolist():
                if info.filename == opf_path:
                    output.writestr(info, replacements[opf_path])
                elif info.filename != cover_archive_name:
                    output.writestr(info, original.read(info.filename))
            if cover_archive_name and cover is not None:
                output.write(cover, cover_archive_name)
    with zipfile.ZipFile(temporary) as validation:
        validation.testzip()
    return temporary


def _write_comic(
    source: Path, metadata: PublicationMetadata, cover: Path | None
) -> Path:
    temporary = _temporary(source)
    values = {
        "Title": metadata.volume_title or metadata.title,
        "Series": metadata.title or metadata.series_name,
        "Number": metadata.volume_index,
        "Summary": metadata.description,
        "Writer": metadata.author,
        "Publisher": metadata.publisher,
        "Genre": ", ".join(metadata.subjects) if metadata.subjects else None,
        "LanguageISO": metadata.language,
    }
    cover_name = f"shuku-cover{cover.suffix.lower() or '.jpg'}" if cover else None
    with (
        zipfile.ZipFile(source, "r") as original,
        zipfile.ZipFile(temporary, "w") as output,
    ):
        comic_info_name = next(
            (
                info.filename
                for info in original.infolist()
                if info.filename.casefold().endswith("comicinfo.xml")
            ),
            None,
        )
        try:
            root = (
                etree.fromstring(
                    original.read(comic_info_name),
                    etree.XMLParser(
                        resolve_entities=False,
                        no_network=True,
                        recover=False,
                        huge_tree=False,
                    ),
                )
                if comic_info_name
                else etree.Element("ComicInfo")
            )
        except (KeyError, etree.XMLSyntaxError):
            root = etree.Element("ComicInfo")
        for name, value in values.items():
            if value in (None, ""):
                continue
            for node in list(root):
                if etree.QName(node).localname == name:
                    root.remove(node)
            etree.SubElement(root, name).text = str(value)
        if cover_name:
            image_names = [
                info.filename
                for info in original.infolist()
                if Path(info.filename).suffix.casefold()
                in {".jpg", ".jpeg", ".png", ".webp", ".gif"}
                and info.filename != cover_name
            ]
            pages = next(
                (node for node in root if etree.QName(node).localname == "Pages"),
                None,
            )
            if pages is None:
                pages = etree.SubElement(root, "Pages")
            for page in list(pages):
                if page.get("Type") == "FrontCover" and page.get("Bookmark") == "Shuku":
                    pages.remove(page)
            page = etree.SubElement(pages, "Page")
            page.set("Image", str(len(image_names)))
            page.set("Type", "FrontCover")
            page.set("Bookmark", "Shuku")
        comic_info = etree.tostring(root, xml_declaration=True, encoding="utf-8")
        for info in original.infolist():
            if (
                info.filename.casefold().endswith("comicinfo.xml")
                or info.filename == cover_name
            ):
                continue
            output.writestr(info, original.read(info.filename))
        output.writestr("ComicInfo.xml", comic_info)
        if cover is not None and cover_name is not None:
            output.write(cover, cover_name)
    with zipfile.ZipFile(temporary) as validation:
        validation.testzip()
    return temporary


def _write_fb2(source: Path, metadata: PublicationMetadata, cover: Path | None) -> Path:
    parser = etree.XMLParser(
        resolve_entities=False, no_network=True, recover=False, huge_tree=False
    )
    try:
        tree = etree.parse(str(source), parser)
    except etree.XMLSyntaxError as exc:
        raise MetadataWritebackError("FB2 XML 无效") from exc
    root = tree.getroot()
    title_info = next(
        (node for node in root.iter() if etree.QName(node).localname == "title-info"),
        None,
    )
    if title_info is None:
        raise MetadataWritebackError("FB2 缺少 title-info")
    namespace = etree.QName(title_info).namespace

    def tag(name: str) -> str:
        return f"{{{namespace}}}{name}" if namespace else name

    desired_nodes = {
        "book-title": bool(metadata.volume_title or metadata.title),
        "author": bool(metadata.authors),
        "annotation": bool(metadata.description),
        "genre": bool(metadata.subjects),
        "lang": bool(metadata.language),
        "date": bool(metadata.published_at),
        "sequence": bool(metadata.series_name),
    }
    for name, should_replace in desired_nodes.items():
        if not should_replace:
            continue
        for node in list(title_info):
            if etree.QName(node).localname == name:
                title_info.remove(node)
    if metadata.volume_title or metadata.title:
        etree.SubElement(title_info, tag("book-title")).text = (
            metadata.volume_title or metadata.title
        )
    for author in metadata.authors:
        author_node = etree.SubElement(title_info, tag("author"))
        etree.SubElement(author_node, tag("nickname")).text = author
    if metadata.description:
        etree.SubElement(title_info, tag("annotation")).text = metadata.description
    for subject in metadata.subjects:
        etree.SubElement(title_info, tag("genre")).text = subject
    if metadata.language:
        etree.SubElement(title_info, tag("lang")).text = metadata.language
    if metadata.published_at:
        etree.SubElement(title_info, tag("date")).text = metadata.published_at
    if metadata.series_name:
        sequence = etree.SubElement(title_info, tag("sequence"))
        sequence.set("name", metadata.series_name)
        if metadata.volume_index is not None:
            sequence.set("number", str(metadata.volume_index))
    if metadata.publisher or metadata.isbn:
        description = next(
            (node for node in root if etree.QName(node).localname == "description"),
            None,
        )
        if description is not None:
            publish_info = next(
                (
                    node
                    for node in description
                    if etree.QName(node).localname == "publish-info"
                ),
                None,
            )
            if publish_info is None:
                publish_info = etree.SubElement(description, tag("publish-info"))
            for name, value in (
                ("publisher", metadata.publisher),
                ("isbn", metadata.isbn),
            ):
                if not value:
                    continue
                for node in list(publish_info):
                    if etree.QName(node).localname == name:
                        publish_info.remove(node)
                etree.SubElement(publish_info, tag(name)).text = value
    if cover is not None:
        for node in list(title_info):
            if etree.QName(node).localname == "coverpage":
                title_info.remove(node)
        coverpage = etree.SubElement(title_info, tag("coverpage"))
        image = etree.SubElement(coverpage, tag("image"))
        image.set("{http://www.w3.org/1999/xlink}href", "#shuku-cover")
        for node in list(root):
            if (
                etree.QName(node).localname == "binary"
                and node.get("id") == "shuku-cover"
            ):
                root.remove(node)
        binary = etree.SubElement(root, tag("binary"))
        binary.set("id", "shuku-cover")
        binary.set("content-type", "image/jpeg")
        binary.text = b64encode(cover.read_bytes()).decode("ascii")
    temporary = _temporary(source)
    tree.write(str(temporary), xml_declaration=True, encoding="utf-8")
    etree.parse(str(temporary), parser)
    return temporary


def _write_pdf(source: Path, metadata: PublicationMetadata) -> Path:
    with source.open("rb") as handle:
        tail = b""
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            if b"/ByteRange" in tail + chunk:
                raise MetadataWritebackError("PDF 包含数字签名")
            tail = chunk[-16:]
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError as exc:
        raise MetadataWritebackError("PDF 写入组件不可用") from exc
    reader = PdfReader(str(source))
    if reader.is_encrypted:
        raise MetadataWritebackError("加密 PDF 不允许改写")
    writer = PdfWriter(clone_from=str(source))
    values = {
        "/Title": metadata.volume_title or metadata.title,
        "/Author": metadata.author,
        "/Subject": metadata.description,
        "/Keywords": ", ".join(metadata.subjects) if metadata.subjects else None,
        "/Series": metadata.title or metadata.series_name,
        "/Volume": metadata.volume_index,
    }
    writer.add_metadata({key: str(value) for key, value in values.items() if value})
    temporary = _temporary(source)
    with temporary.open("wb") as output:
        writer.write(output)
    PdfReader(str(temporary))
    return temporary


def _write_audio(
    source: Path, metadata: PublicationMetadata, cover: Path | None
) -> Path:
    try:
        import mutagen
    except ImportError as exc:
        raise MetadataWritebackError("音频元数据组件不可用") from exc
    temporary = _temporary(source)
    shutil.copyfile(source, temporary)
    audio = mutagen.File(str(temporary), easy=True)
    if audio is None:
        temporary.unlink(missing_ok=True)
        raise MetadataWritebackError("音频容器不支持标签写入")
    if audio.tags is None:
        audio.add_tags()
    values = {
        "album": metadata.title,
        "albumartist": metadata.author,
        "genre": list(metadata.subjects) if metadata.subjects else None,
        "date": metadata.published_at,
        "comment": metadata.description,
    }
    for key, value in values.items():
        if value not in (None, "", []):
            try:
                audio[key] = value if isinstance(value, list) else [str(value)]
            except (KeyError, TypeError):
                continue
    audio.save()
    if cover is not None:
        _write_audio_cover(temporary, cover)
    if mutagen.File(str(temporary), easy=True) is None:
        raise MetadataWritebackError("音频标签写入后无法复读")
    return temporary


def _write_audio_cover(audio_path: Path, cover: Path) -> None:
    content = cover.read_bytes()
    mime = "image/png" if cover.suffix.casefold() == ".png" else "image/jpeg"
    try:
        if audio_path.suffix.casefold() == ".mp3":
            from mutagen.id3 import APIC, ID3

            tags = ID3(str(audio_path))
            tags.delall("APIC")
            tags.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=content))
            tags.save(str(audio_path))
        elif audio_path.suffix.casefold() == ".flac":
            from mutagen.flac import FLAC, Picture

            audio = FLAC(str(audio_path))
            picture = Picture()
            picture.type = 3
            picture.mime = mime
            picture.desc = "Cover"
            picture.data = content
            audio.clear_pictures()
            audio.add_picture(picture)
            audio.save()
        elif audio_path.suffix.casefold() in {".m4a", ".m4b", ".mp4"}:
            from mutagen.mp4 import MP4, MP4Cover

            mp4_audio = MP4(str(audio_path))
            image_format = (
                MP4Cover.FORMAT_PNG if mime == "image/png" else MP4Cover.FORMAT_JPEG
            )
            mp4_audio["covr"] = [MP4Cover(content, imageformat=image_format)]
            mp4_audio.save()
    except (KeyError, TypeError, ValueError):
        return


def prepare_writeback(
    source_path: str, payload: dict[str, object], storage_root: Path
) -> PreparedWriteback:
    source = Path(source_path).expanduser().resolve()
    _validate_source(source, payload)
    metadata, cover = _publication(payload, storage_root)
    suffix = source.suffix.lower()
    output = source
    temporary: Path
    warning_code: str | None = None
    try:
        if suffix == ".epub":
            temporary = _write_epub(source, metadata, cover)
        elif suffix == ".pdf":
            temporary = _write_pdf(source, metadata)
        elif suffix in {".cbz", ".zip"}:
            temporary = _write_comic(source, metadata, cover)
        elif suffix == ".fb2":
            temporary = _write_fb2(source, metadata, cover)
        elif suffix in SIDECAR_SUFFIXES or source.is_dir():
            temporary, output = _write_sidecar(source, metadata, cover)
        else:
            try:
                temporary = _write_audio(source, metadata, cover)
            except MetadataWritebackError:
                temporary, output = _write_sidecar(source, metadata, cover)
                warning_code = "SIDECAR_FALLBACK"
    except MetadataWritebackError:
        if suffix in {".pdf"}:
            temporary, output = _write_sidecar(source, metadata, cover)
            warning_code = "SIDECAR_FALLBACK"
        else:
            raise
    return PreparedWriteback(
        prepared_path=temporary,
        output_path=output,
        output_hash=_hash(temporary),
        written_fields=metadata.populated_fields,
        warning_code=warning_code,
    )


def output_path_for(source_path: str, prepared_path: str) -> Path:
    source = Path(source_path).expanduser().resolve()
    prepared = Path(prepared_path)
    if (
        prepared.parent == source.parent
        and source.is_file()
        and prepared.name.startswith(f".{source.name}.")
    ):
        return source
    if source.is_dir():
        return source / "metadata.opf"
    if prepared.parent == source.parent and prepared.name.startswith(
        f".{source.with_suffix('.opf').name}."
    ):
        return source.with_suffix(".opf")
    return source


def publish_prepared(
    source_path: str, prepared_path: str, expected_hash: str
) -> tuple[Path, int, int]:
    prepared = Path(prepared_path)
    output = output_path_for(source_path, prepared_path)
    if output.is_file() and _hash(output) == expected_hash:
        prepared.unlink(missing_ok=True)
    else:
        if not prepared.is_file() or _hash(prepared) != expected_hash:
            raise MetadataWritebackError("预备文件丢失或校验失败")
        os.replace(prepared, output)
    stat = output.stat()
    return output, stat.st_size, int(stat.st_mtime * 1000)
