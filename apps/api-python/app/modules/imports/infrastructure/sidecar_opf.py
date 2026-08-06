"""Safe filesystem discovery for publication OPF sidecars."""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass, fields
from pathlib import Path, PurePosixPath

from app.contracts.publication_metadata import PublicationMetadata
from app.modules.metadata.public import (
    MAX_OPF_BYTES,
    OpfMetadataError,
    parse_opf_metadata,
)

MAX_SIDECAR_COVER_BYTES = 20 * 1024 * 1024
IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


@dataclass(frozen=True, slots=True)
class SidecarOpfResult:
    metadata: PublicationMetadata
    source_kind: str
    opf_path: Path
    cover_path: Path | None
    field_sources: tuple[tuple[str, str], ...]


def _candidate_paths(
    source: Path, *, directory_fallback: bool
) -> tuple[tuple[Path, str], ...]:
    resolved = source.expanduser().resolve()
    candidates: list[tuple[Path, str]] = []
    if resolved.is_file():
        candidates.append((resolved.with_suffix(".opf"), "FILE"))
        directory = resolved.parent
    else:
        directory = resolved
    if directory_fallback:
        candidates.extend(
            (
                (directory / "metadata.opf", "DIRECTORY_METADATA"),
                (directory / f"{directory.name}.opf", "DIRECTORY_NAMED"),
            )
        )
    unique: list[tuple[Path, str]] = []
    seen: set[Path] = set()
    for path, kind in candidates:
        if path not in seen:
            unique.append((path, kind))
            seen.add(path)
    return tuple(unique)


def _safe_cover(opf_path: Path, href: str | None) -> Path | None:
    if not href:
        return None
    relative = PurePosixPath(href.replace("\\", "/"))
    if relative.is_absolute() or ".." in relative.parts:
        return None
    root = opf_path.parent.resolve()
    unresolved = root / Path(*relative.parts)
    if unresolved.is_symlink():
        return None
    candidate = unresolved.resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    if not candidate.is_file() or candidate.is_symlink():
        return None
    try:
        size = candidate.stat().st_size
    except OSError:
        return None
    mime_type = mimetypes.guess_type(candidate.name)[0]
    if (
        size <= 0
        or size > MAX_SIDECAR_COVER_BYTES
        or mime_type not in IMAGE_MIME_TYPES
        or not _has_image_signature(candidate)
    ):
        return None
    return candidate


def _has_image_signature(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            prefix = handle.read(16)
    except OSError:
        return False
    return prefix.startswith(
        (b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"GIF87a", b"GIF89a")
    ) or (prefix.startswith(b"RIFF") and prefix[8:12] == b"WEBP")


def discover_sidecar_opf(
    source: Path, *, directory_fallback: bool
) -> SidecarOpfResult | None:
    parsed: list[tuple[PublicationMetadata, str, Path, Path | None]] = []
    for candidate, source_kind in _candidate_paths(
        source, directory_fallback=directory_fallback
    ):
        if not candidate.is_file() or candidate.is_symlink():
            continue
        try:
            if candidate.stat().st_size > MAX_OPF_BYTES:
                continue
            metadata = parse_opf_metadata(candidate.read_bytes())
        except (OSError, OpfMetadataError):
            continue
        parsed.append(
            (
                metadata,
                source_kind,
                candidate,
                _safe_cover(candidate, metadata.cover_href),
            )
        )
    if not parsed:
        return None
    merged = PublicationMetadata()
    evidence: dict[str, str] = {}
    cover_path: Path | None = None
    for metadata, source_kind, _path, candidate_cover in reversed(parsed):
        for definition in fields(PublicationMetadata):
            name = definition.name
            value = getattr(metadata, name)
            if value not in (None, "", ()):
                evidence[name] = source_kind
        merged = _merge_metadata(merged, metadata)
        if candidate_cover is not None:
            cover_path = candidate_cover
            evidence["cover"] = source_kind
    _highest_metadata, highest_kind, highest_path, _highest_cover = parsed[0]
    return SidecarOpfResult(
        metadata=merged,
        source_kind=highest_kind,
        opf_path=highest_path,
        cover_path=cover_path,
        field_sources=tuple(evidence.items()),
    )


def _merge_metadata(
    current: PublicationMetadata, preferred: PublicationMetadata
) -> PublicationMetadata:
    return PublicationMetadata(
        title=preferred.title or current.title,
        volume_title=preferred.volume_title or current.volume_title,
        authors=preferred.authors or current.authors,
        narrators=preferred.narrators or current.narrators,
        abridged=preferred.abridged
        if preferred.abridged is not None
        else current.abridged,
        description=preferred.description or current.description,
        subjects=preferred.subjects or current.subjects,
        series_name=preferred.series_name or current.series_name,
        series_index=(
            preferred.series_index
            if preferred.series_index is not None
            else current.series_index
        ),
        volume_index=(
            preferred.volume_index
            if preferred.volume_index is not None
            else current.volume_index
        ),
        language=preferred.language or current.language,
        publisher=preferred.publisher or current.publisher,
        published_at=preferred.published_at or current.published_at,
        identifier=preferred.identifier or current.identifier,
        isbn=preferred.isbn or current.isbn,
        cover_href=preferred.cover_href or current.cover_href,
        unparsed_values=preferred.unparsed_values or current.unparsed_values,
    )
