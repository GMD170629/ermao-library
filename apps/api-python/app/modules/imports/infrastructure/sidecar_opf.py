"""Safe filesystem discovery for publication OPF sidecars."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from app.contracts.publication_metadata import PublicationMetadata
from app.modules.metadata.public import (
    MAX_OPF_BYTES,
    OpfMetadataError,
    parse_opf_metadata,
)

MAX_SIDECAR_COVER_BYTES = 20 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class SidecarOpfResult:
    metadata: PublicationMetadata
    cover_content: bytes | None


def discover_sidecar_opf(source: Path) -> SidecarOpfResult | None:
    candidates = (
        source.with_suffix(".opf"),
        source.parent / "metadata.opf",
        source.parent / f"{source.parent.name}.opf",
    )
    for candidate in candidates:
        if not candidate.is_file() or candidate.is_symlink():
            continue
        try:
            if candidate.stat().st_size > MAX_OPF_BYTES:
                continue
            metadata = parse_opf_metadata(candidate.read_bytes())
        except (OSError, OpfMetadataError):
            continue
        return SidecarOpfResult(
            metadata=metadata,
            cover_content=_safe_cover_content(candidate, metadata.cover_href),
        )
    return None


def _safe_cover_content(opf_path: Path, href: str | None) -> bytes | None:
    if not href:
        return None
    relative = PurePosixPath(href.replace("\\", "/"))
    if relative.is_absolute() or ".." in relative.parts:
        return None
    root = opf_path.parent.resolve()
    unresolved = root.joinpath(*relative.parts)
    if unresolved.is_symlink():
        return None
    try:
        candidate = unresolved.resolve(strict=True)
        candidate.relative_to(root)
        if not candidate.is_file() or candidate.is_symlink():
            return None
        content = candidate.read_bytes()
    except (OSError, ValueError):
        return None
    if not 0 < len(content) <= MAX_SIDECAR_COVER_BYTES or not _image_signature(content):
        return None
    return content


def _image_signature(content: bytes) -> bool:
    prefix = content[:16]
    return prefix.startswith(
        (b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"GIF87a", b"GIF89a")
    ) or (prefix.startswith(b"RIFF") and prefix[8:12] == b"WEBP")


__all__ = ["SidecarOpfResult", "discover_sidecar_opf"]
