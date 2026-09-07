from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.modules.imports.infrastructure.library_root import resolve_library_root_path
from app.modules.imports.public import LibraryPathError


def test_scandir_permission_error_overrides_readable_access(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    assert os.access(root, os.R_OK) is True
    denied = PermissionError("directory enumeration denied")

    with (
        patch("os.scandir", side_effect=denied) as scandir,
        pytest.raises(LibraryPathError) as raised,
    ):
        resolve_library_root_path(str(root))

    scandir.assert_called_once_with(root)
    assert raised.value.code == "INVALID_LIBRARY_PATH"
    assert raised.value.status_code == 400
    assert raised.value.__cause__ is denied


@pytest.mark.parametrize("populated", [False, True], ids=["empty", "nonempty"])
def test_readable_root_is_resolved_without_changing_originals(
    tmp_path: Path, populated: bool
) -> None:
    root = tmp_path / "library"
    root.mkdir()
    originals = {"book.epub": b"original publication\x00\xff"} if populated else {}
    for name, content in originals.items():
        (root / name).write_bytes(content)

    resolved = resolve_library_root_path(str(root / ".." / root.name))

    assert resolved == root.resolve()
    assert {entry.name for entry in root.iterdir()} == set(originals)
    for name, content in originals.items():
        assert (root / name).read_bytes() == content


def test_root_probe_reads_one_entry_and_closes_scandir(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    (root / "first.epub").write_bytes(b"first")
    (root / "second.epub").write_bytes(b"second")

    with os.scandir(root) as entries:
        probe = MagicMock(wraps=entries)
        probe.__enter__.return_value = probe
        probe.__iter__.side_effect = lambda: probe
        probe.__next__.side_effect = entries.__next__
        probe.__exit__.side_effect = entries.__exit__
        with patch("os.scandir", return_value=probe) as scandir:
            resolved = resolve_library_root_path(str(root))

        assert resolved == root
        scandir.assert_called_once_with(root)
        probe.__next__.assert_called_once_with()
        # One entry remains unless the underlying directory handle was closed.
        assert list(entries) == []


@pytest.mark.parametrize(
    ("path_kind", "status_code"),
    [("empty", 400), ("relative", 400), ("file", 400), ("missing", 404)],
)
def test_invalid_root_keeps_existing_error_contract(
    tmp_path: Path, path_kind: str, status_code: int
) -> None:
    original = tmp_path / "book.epub"
    original.write_bytes(b"original publication")
    paths = {
        "empty": "",
        "relative": "relative-library",
        "file": str(original),
        "missing": str(tmp_path / "missing-library"),
    }

    with pytest.raises(LibraryPathError) as raised:
        resolve_library_root_path(paths[path_kind])

    assert raised.value.code == "INVALID_LIBRARY_PATH"
    assert raised.value.status_code == status_code
