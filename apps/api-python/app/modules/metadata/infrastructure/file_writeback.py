"""Prepare and atomically publish OPF sidecars without mutating source books."""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from dataclasses import dataclass, replace
from pathlib import Path

# lxml is validated at this adapter boundary and lacks PEP 561 metadata.
from lxml import etree  # type: ignore[import-untyped]

from app.contracts.publication_metadata import PublicationMetadata
from app.modules.metadata.application.opf import (
    OPF_NAMESPACE,
    OpfMetadataError,
    cover_media_type,
    parse_opf_metadata,
    serialize_opf_metadata,
)


class MetadataWritebackError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PreparedWriteback:
    prepared_path: Path
    output_path: Path
    written_fields: tuple[str, ...]
    warning_code: str | None = None


ORPHAN_PREPARED_MAX_AGE_SECONDS = 24 * 60 * 60
ORPHAN_PREPARED_SCAN_LIMIT = 256


def cleanup_orphan_prepared_files(
    source_directories: tuple[Path, ...],
    *,
    protected_paths: frozenset[Path] = frozenset(),
    now_seconds: float | None = None,
    max_age_seconds: int = ORPHAN_PREPARED_MAX_AGE_SECONDS,
    scan_limit: int = ORPHAN_PREPARED_SCAN_LIMIT,
) -> int:
    """Remove bounded, stale OPF preparation files from known source directories."""

    cutoff = (time.time() if now_seconds is None else now_seconds) - max_age_seconds
    protected = frozenset(path.resolve() for path in protected_paths)
    scanned = 0
    removed = 0
    for directory in dict.fromkeys(source_directories):
        if scanned >= scan_limit:
            break
        if directory.is_symlink():
            continue
        try:
            resolved_directory = directory.resolve()
        except OSError:
            continue
        if not resolved_directory.is_dir():
            continue
        try:
            candidates = resolved_directory.glob(".*.shuku-*.part")
            for candidate in candidates:
                if scanned >= scan_limit:
                    break
                scanned += 1
                try:
                    resolved_candidate = candidate.resolve()
                    resolved_candidate.relative_to(resolved_directory)
                    stat = candidate.lstat()
                except (OSError, ValueError):
                    continue
                if (
                    resolved_candidate in protected
                    or candidate.is_symlink()
                    or not candidate.is_file()
                    or stat.st_mtime > cutoff
                ):
                    continue
                try:
                    candidate.unlink()
                except OSError:
                    continue
                removed += 1
        except OSError:
            continue
    return removed


def _publication(
    payload: dict[str, object], storage_root: Path
) -> tuple[PublicationMetadata, Path | None]:
    authors = payload.get("authors")
    subjects = payload.get("subjects")
    narrators = payload.get("narrators")
    abridged_value = payload.get("abridged")
    abridged = abridged_value if isinstance(abridged_value, bool) else None
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
        volume_title=str(payload.get("resourceTitle") or "").strip() or None,
        authors=tuple(str(item).strip() for item in authors if str(item).strip())
        if isinstance(authors, list)
        else (),
        narrators=tuple(str(item).strip() for item in narrators if str(item).strip())
        if isinstance(narrators, list)
        else (),
        abridged=abridged,
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
    if source.is_dir():
        return source / "metadata.opf"
    output = source.with_suffix(".opf")
    if output == source:
        raise MetadataWritebackError("OPF 元数据文件不能作为源图书")
    return output


def _publish_sidecar_cover(
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


def _metadata_element(metadata: PublicationMetadata) -> etree._Element:
    document = etree.fromstring(serialize_opf_metadata(metadata))
    return next(node for node in document if etree.QName(node).localname == "metadata")


def _overlay_metadata(
    existing: PublicationMetadata, desired: PublicationMetadata
) -> PublicationMetadata:
    return replace(desired, unparsed_values=existing.unparsed_values)


def _replace_package_metadata(
    package: etree._Element, metadata: PublicationMetadata
) -> None:
    package_metadata = next(
        (node for node in package if etree.QName(node).localname == "metadata"), None
    )
    if package_metadata is None and etree.QName(package).localname == "metadata":
        package_metadata = package
    if package_metadata is None:
        raise MetadataWritebackError("OPF 缺少 metadata")
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
        "shuku:series_index",
        "shuku:abridged",
        "belongs-to-collection",
        "group-position",
        "cover",
    }
    for child in list(package_metadata):
        local = etree.QName(child).localname
        name = str(child.get("name") or child.get("property") or "").casefold()
        role = str(
            child.get(f"{{{OPF_NAMESPACE}}}role") or child.get("role") or ""
        ).casefold()
        managed_narrator = local == "contributor" and role in {"nrt", "narrator"}
        if (
            local in managed
            or managed_narrator
            or (local == "meta" and name in managed_meta)
        ):
            package_metadata.remove(child)
    replacement = _metadata_element(metadata)
    for child in replacement:
        package_metadata.append(child)


def _set_cover_manifest(package: etree._Element, href: str | None) -> None:
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
    if href is None:
        if cover_item is not None:
            manifest.remove(cover_item)
        return
    if cover_item is None:
        cover_item = etree.SubElement(manifest, "item")
        cover_item.set("id", "cover-image")
    cover_item.set("href", href)
    cover_item.set("media-type", cover_media_type(href))
    cover_item.set("properties", "cover-image")


def _write_sidecar(
    source: Path, metadata: PublicationMetadata, cover: Path | None
) -> tuple[Path, Path]:
    output = _sidecar_output(source)
    metadata = _publish_sidecar_cover(metadata, cover, output)
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
            _set_cover_manifest(package, merged.cover_href)
            content = etree.tostring(package, xml_declaration=True, encoding="utf-8")
        except (OSError, OpfMetadataError, etree.XMLSyntaxError):
            content = None
    temporary.write_bytes(content or serialize_opf_metadata(metadata))
    return temporary, output


def prepare_writeback(
    source_path: str, payload: dict[str, object], storage_root: Path
) -> PreparedWriteback:
    source = Path(source_path).expanduser().resolve()
    _validate_source(source, payload)
    metadata, cover = _publication(payload, storage_root)
    temporary, output = _write_sidecar(source, metadata, cover)
    return PreparedWriteback(
        prepared_path=temporary,
        output_path=output,
        written_fields=metadata.populated_fields,
    )


def output_path_for(source_path: str, prepared_path: str) -> Path:
    source = Path(source_path).expanduser().resolve()
    prepared = Path(prepared_path)
    if source.is_dir():
        output = source / "metadata.opf"
    else:
        output = source.with_suffix(".opf")
        if output == source:
            raise MetadataWritebackError("OPF 元数据文件不能作为源图书")
    if prepared.parent == output.parent and prepared.name.startswith(
        f".{output.name}.shuku-"
    ):
        return output
    raise MetadataWritebackError("预备文件不是有效的 OPF 旁车文件")


def publish_prepared(source_path: str, prepared_path: str) -> tuple[Path, int, int]:
    prepared = Path(prepared_path)
    output = output_path_for(source_path, prepared_path)
    if prepared.is_file() and not prepared.is_symlink():
        os.replace(prepared, output)
    elif not output.is_file() or output.is_symlink():
        raise MetadataWritebackError("预备文件丢失")
    stat = output.stat()
    return output, stat.st_size, int(stat.st_mtime * 1000)
