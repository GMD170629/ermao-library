from pathlib import Path

from app.modules.library.infrastructure.source_paths import (
    resolve_existing_library_file,
)


def test_path_resolves_existing_file_without_changing_its_name(tmp_path: Path) -> None:
    source = tmp_path / "中文 目录" / "Book 1.epub"
    source.parent.mkdir()
    source.write_bytes(b"original")
    assert (
        resolve_existing_library_file(str(tmp_path), "中文 目录/Book 1.epub") == source
    )
    assert source.read_bytes() == b"original"


def test_missing_directory_and_escaping_paths_have_no_display_path(
    tmp_path: Path,
) -> None:
    root = tmp_path / "library"
    root.mkdir()
    outside = tmp_path / "outside.epub"
    outside.write_bytes(b"original")
    (root / "linked.epub").symlink_to(outside)
    for relative in ["missing.epub", ".", "../outside.epub", "linked.epub"]:
        assert resolve_existing_library_file(str(root), relative) is None
