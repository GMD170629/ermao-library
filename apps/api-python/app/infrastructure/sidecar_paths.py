"""Canonical OPF sidecar candidate names shared by import and explicit file operations."""

import unicodedata
from pathlib import Path


def sidecar_opf_paths(source: Path, *, directory: bool) -> tuple[Path, ...]:
    if directory:
        return (
            source / "metadata.opf",
            source / f"{source.name}.opf",
            source.with_suffix(".opf"),
        )
    return (
        source.with_suffix(".opf"),
        source.parent / "metadata.opf",
        source.parent / f"{source.parent.name}.opf",
    )


def same_stem_source_names(names: tuple[str, ...], source_name: str) -> tuple[str, ...]:
    """Find publication peers that would claim the same OPF sidecar."""
    stem = unicodedata.normalize("NFC", Path(source_name).stem).casefold()
    sidecars = {".opf", ".jpg", ".jpeg", ".png", ".webp", ".gif"}
    return tuple(
        name
        for name in names
        if unicodedata.normalize("NFC", Path(name).stem).casefold() == stem
        and Path(name).suffix.lower() not in sidecars
    )
