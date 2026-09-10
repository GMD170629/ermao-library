from pathlib import Path

from app.modules.media.public import versioned_cover_url


def test_cover_identity_rejects_default_and_escaped_files(test_settings, tmp_path: Path):
    root = test_settings.resolved_storage_root
    root.mkdir(parents=True)
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"image")
    (root / "escape.png").symlink_to(outside)
    for value in (None, "", "covers/default-book-cover-v1.png", str(outside), "../outside.png", "escape.png"):
        assert versioned_cover_url("/api/books/b/cover", value, test_settings) == ""
