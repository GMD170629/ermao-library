from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from app.modules.catalog.public import (
    AdmissionKind,
    AssetCandidate,
    EntryType,
    ProbedEntry,
    SidecarRole,
    SourceFormat,
    SourceKind,
    VolumeCandidate,
)


def test_catalog_public_import_does_not_load_framework_or_legacy_import_modules() -> (
    None
):
    source_root = Path(__file__).parents[4]
    script = """
import sys
import app.modules.catalog.public

for name in sys.modules:
    assert not name == 'fastapi' and not name.startswith('fastapi.'), name
    assert not name == 'sqlalchemy' and not name.startswith('sqlalchemy.'), name
    assert not name.startswith('app.modules.imports'), name
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=source_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_catalog_public_module_exposes_only_named_domain_contracts() -> None:
    from app.modules.catalog import public

    assert public.__name__ == "app.modules.catalog.public"
    assert hasattr(public, "OrganizationMode")
    assert hasattr(public, "EntryType")
    assert hasattr(public, "AdmissionKind")
    assert hasattr(public, "PathComparison")
    assert hasattr(public, "ViolationCode")
    assert hasattr(public, "ProbedEntry")
    assert hasattr(public, "interpret_layout")


def test_probed_entry_requires_sidecar_role_and_file_entry_type() -> None:
    with pytest.raises(ValueError):
        ProbedEntry(
            relative_path=("book.opf",),
            entry_type=EntryType.FILE,
            admission=AdmissionKind.SIDECAR,
        )

    sidecar = ProbedEntry(
        relative_path=("book.opf",),
        entry_type=EntryType.FILE,
        admission=AdmissionKind.SIDECAR,
        sidecar_role=SidecarRole.OPF,
    )
    assert sidecar.sidecar_role is SidecarRole.OPF

    with pytest.raises(ValueError):
        ProbedEntry(
            relative_path=("nested",),
            entry_type=EntryType.DIRECTORY,
            admission=AdmissionKind.SIDECAR,
            sidecar_role=SidecarRole.ARTWORK,
        )

    with pytest.raises(ValueError):
        ProbedEntry(
            relative_path=("book.epub",),
            entry_type=EntryType.FILE,
            admission=AdmissionKind.PRIMARY,
            source_format=SourceFormat.EPUB,
            sidecar_role=SidecarRole.OPF,
        )


def _asset(path: tuple[str, ...], order: int = 0) -> AssetCandidate:
    return AssetCandidate(path=path, source_format=SourceFormat.EPUB, order=order)


def _candidate(
    *,
    work_path: tuple[str, ...],
    version_path: tuple[str, ...] | None,
    volume_path: tuple[str, ...],
    source_kind: SourceKind = SourceKind.SINGLE_FILE,
    assets: tuple[AssetCandidate, ...] | None = None,
) -> VolumeCandidate:
    return VolumeCandidate(
        work_path=work_path,
        version_path=version_path,
        volume_path=volume_path,
        source_kind=source_kind,
        assets=assets or (_asset(volume_path),),
    )


def test_volume_candidate_rejects_invalid_work_version_volume_relationships() -> None:
    with pytest.raises(ValueError):
        _candidate(
            work_path=("work",),
            version_path=("other", "version"),
            volume_path=("other", "version", "book.epub"),
        )

    with pytest.raises(ValueError):
        _candidate(
            work_path=("work",),
            version_path=("work", "version"),
            volume_path=("work", "other", "book.epub"),
        )

    with pytest.raises(ValueError):
        _candidate(
            work_path=("work",),
            version_path=("work", "series", "version"),
            volume_path=("work", "series", "version", "book.epub"),
        )

    with pytest.raises(ValueError):
        _candidate(
            work_path=("work",),
            version_path=None,
            volume_path=("other", "book.epub"),
        )

    with pytest.raises(ValueError):
        _candidate(
            work_path=("work",),
            version_path=None,
            volume_path=("work", "nested", "book.epub"),
        )


def test_volume_candidate_rejects_assets_outside_the_volume_boundary() -> None:
    with pytest.raises(ValueError):
        _candidate(
            work_path=("work",),
            version_path=("work", "version"),
            volume_path=("work", "version", "book.epub"),
            assets=(_asset(("work", "version", "other.epub")),),
        )

    with pytest.raises(ValueError):
        _candidate(
            work_path=("work",),
            version_path=("work", "version"),
            volume_path=("work", "version", "audio"),
            source_kind=SourceKind.MULTI_ASSET_AUDIO,
            assets=(
                _asset(("work", "version", "audio", "track-01.mp3")),
                _asset(("work", "version", "other", "track-02.mp3"), order=1),
            ),
        )
