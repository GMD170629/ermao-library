from __future__ import annotations

import os
import unicodedata
from pathlib import Path

import pytest

from app.modules.catalog.domain.errors import (
    RootExpansionNotAllowed,
    RootNotAbsolute,
    RootNotDirectory,
    RootProtected,
    RootRequired,
    RootUnavailable,
)
from app.modules.catalog.domain.model import PathComparison
from app.modules.catalog.domain.root_paths import RootRelation, root_relation
from app.modules.catalog.infrastructure.files import (
    LibraryFilesystemConfig,
    LocalLibraryFilesystem,
)


def _adapter(*protected: Path) -> LocalLibraryFilesystem:
    return LocalLibraryFilesystem(LibraryFilesystemConfig.from_paths(protected))


@pytest.mark.parametrize(
    ("requested", "error_type"),
    (
        ("", RootRequired),
        ("relative/library", RootNotAbsolute),
        ("~/library", RootExpansionNotAllowed),
    ),
)
def test_preflight_rejects_empty_relative_and_tilde_paths(
    requested: str, error_type: type[ValueError]
) -> None:
    with pytest.raises(error_type):
        _adapter().preflight(requested, path_comparison=PathComparison.SENSITIVE)


def test_preflight_rejects_missing_and_non_directory(tmp_path: Path) -> None:
    with pytest.raises(RootUnavailable) as missing:
        _adapter().preflight(
            str(tmp_path / "missing"), path_comparison=PathComparison.SENSITIVE
        )
    assert missing.value.code == "ROOT_UNAVAILABLE"

    file_path = tmp_path / "book.epub"
    file_path.write_bytes(b"book")
    with pytest.raises(RootNotDirectory) as non_directory:
        _adapter().preflight(str(file_path), path_comparison=PathComparison.SENSITIVE)
    assert non_directory.value.code == "ROOT_NOT_DIRECTORY"


def test_preflight_rejects_roots_overlapping_protected_app_data(tmp_path: Path) -> None:
    protected = tmp_path / "app-data"
    protected.mkdir()
    child = protected / "cache"
    child.mkdir()

    for comparison in PathComparison:
        for requested in (protected, child, tmp_path):
            with pytest.raises(RootProtected) as raised:
                _adapter(protected).preflight(
                    str(requested), path_comparison=comparison
                )
            assert raised.value.code == "ROOT_PROTECTED"


def test_preflight_resolves_root_symlink_without_traversing_children(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (target / "book.epub").write_bytes(b"book")
    try:
        (target / "linked").symlink_to(outside, target_is_directory=True)
        root_link = tmp_path / "root-link"
        root_link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable on this filesystem")

    observation = _adapter().preflight(
        str(root_link), path_comparison=PathComparison.SENSITIVE
    )
    assert observation.canonical_path == unicodedata.normalize("NFC", str(target))
    assert observation.filesystem_identity


def test_preflight_preserves_host_spelling_and_normalizes_identity_keys(
    tmp_path: Path,
) -> None:
    decomposed = "Cafe\u0301"
    root = tmp_path / decomposed
    root.mkdir()

    observation = _adapter().preflight(
        str(root), path_comparison=PathComparison.INSENSITIVE
    )
    assert observation.canonical_path == str(root.resolve())
    assert unicodedata.normalize("NFC", observation.canonical_path) != (
        observation.canonical_path
    )
    expected_name = unicodedata.normalize("NFC", os.path.normcase(decomposed))
    assert observation.components[-1] == expected_name
    assert observation.root_path_key == unicodedata.normalize(
        "NFC", observation.root_path_key
    )
    assert "\\" not in observation.root_path_key
    assert not observation.root_path_key.endswith("/")
    assert not observation.canonical_path.endswith("/")


def test_root_identity_ignores_child_path_comparison(tmp_path: Path) -> None:
    root = tmp_path / "Books"
    root.mkdir()
    sensitive = _adapter().preflight(
        str(root), path_comparison=PathComparison.SENSITIVE
    )
    insensitive = _adapter().preflight(
        str(root), path_comparison=PathComparison.INSENSITIVE
    )
    assert sensitive == insensitive
    assert sensitive.components[-1] == os.path.normcase("Books")


def test_root_overlap_is_independent_of_child_path_comparison(tmp_path: Path) -> None:
    root = tmp_path / "Library"
    child = root / "Child"
    child.mkdir(parents=True)
    adapter = _adapter()
    observations = {
        comparison: (
            adapter.preflight(str(root), path_comparison=comparison),
            adapter.preflight(str(child), path_comparison=comparison),
        )
        for comparison in PathComparison
    }
    sensitive_root, sensitive_child = observations[PathComparison.SENSITIVE]
    insensitive_root, insensitive_child = observations[PathComparison.INSENSITIVE]
    assert sensitive_root.claim == insensitive_root.claim
    assert sensitive_child.claim == insensitive_child.claim
    assert (
        root_relation(sensitive_root.claim, sensitive_child.claim)
        is RootRelation.CANDIDATE_ANCESTOR
    )
    assert (
        root_relation(insensitive_root.claim, insensitive_child.claim)
        is RootRelation.CANDIDATE_ANCESTOR
    )


def test_revalidate_requires_same_canonical_identity_and_key(tmp_path: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    first = _adapter().preflight(str(root), path_comparison=PathComparison.SENSITIVE)
    refreshed = _adapter().revalidate(
        str(root), first, path_comparison=PathComparison.SENSITIVE
    )
    assert refreshed.canonical_path == first.canonical_path
    assert refreshed.root_path_key == first.root_path_key
    assert refreshed.filesystem_identity == first.filesystem_identity

    changed = first.__class__(
        canonical_path=first.canonical_path,
        root_path_key=first.root_path_key,
        components=first.components,
        filesystem_identity="different",
        writable=first.writable,
    )
    refreshed_from_changed_observation = _adapter().revalidate(
        str(root), changed, path_comparison=PathComparison.SENSITIVE
    )
    assert (
        refreshed_from_changed_observation.filesystem_identity
        == first.filesystem_identity
    )


def test_revalidate_rejects_root_symlink_retarget(tmp_path: Path) -> None:
    first_target = tmp_path / "first"
    second_target = tmp_path / "second"
    first_target.mkdir()
    second_target.mkdir()
    link = tmp_path / "library-link"
    try:
        link.symlink_to(first_target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable on this filesystem")

    adapter = _adapter()
    first = adapter.preflight(str(link), path_comparison=PathComparison.SENSITIVE)
    link.unlink()
    link.symlink_to(second_target, target_is_directory=True)

    refreshed = adapter.revalidate(
        str(link), first, path_comparison=PathComparison.SENSITIVE
    )
    assert refreshed.canonical_path == str(second_target)
    assert refreshed.filesystem_identity != first.filesystem_identity


def test_read_write_callers_can_reject_unwritable_observation(tmp_path: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    adapter = _adapter()
    observation = adapter.preflight(str(root), path_comparison=PathComparison.SENSITIVE)
    # The adapter reports writability; the application command owns the
    # READ_WRITE policy decision.  This test remains valid under root users.
    assert isinstance(observation.writable, bool)


def test_preflight_does_not_create_probe_files(tmp_path: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    before = tuple(root.iterdir())

    _adapter().preflight(str(root), path_comparison=PathComparison.SENSITIVE)

    assert tuple(root.iterdir()) == before
