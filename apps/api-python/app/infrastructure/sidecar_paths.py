"""Canonical OPF sidecar candidate names shared by import and explicit file operations."""

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
