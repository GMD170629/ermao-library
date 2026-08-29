from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Self

import pytest
from PIL import Image

from app.modules.library.application.recognized_metadata import MetadataTargetScope
from app.modules.library.infrastructure import recognized_metadata
from app.modules.library.infrastructure.recognized_metadata import (
    FilesystemRecognizedCoverPublication,
    SafeRemoteCoverDownloader,
)
from app.modules.media.public import UnsafeCoverUrl


def _image_bytes(image_format: str = "PNG") -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (4, 4), color=(20, 40, 60)).save(buffer, format=image_format)
    return buffer.getvalue()


def test_remote_cover_rejects_non_public_targets_before_network_access() -> None:
    downloader = SafeRemoteCoverDownloader()

    with pytest.raises(UnsafeCoverUrl):
        downloader.download("http://127.0.0.1/private-cover.png")


class _Response:
    def __init__(self, *, content_type: str, content: bytes) -> None:
        self.headers = {"content-type": content_type}
        self._content = content

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, limit: int) -> bytes:
        return self._content[:limit]


class _Opener:
    def __init__(self, response: _Response) -> None:
        self._response = response

    def open(self, _request: object, timeout: int) -> _Response:
        assert timeout == 20
        return self._response


@pytest.mark.parametrize(
    ("content_type", "content"),
    [
        ("text/html", _image_bytes()),
        ("image/png", b"x" * (10 * 1024 * 1024 + 1)),
    ],
    ids=("wrong-mime", "oversized"),
)
def test_remote_cover_rejects_wrong_mime_and_oversized_responses(
    monkeypatch,
    content_type: str,
    content: bytes,
) -> None:
    monkeypatch.setattr(recognized_metadata, "validate_cover_url", lambda url: url)
    monkeypatch.setattr(
        recognized_metadata,
        "build_opener",
        lambda *_handlers: _Opener(
            _Response(content_type=content_type, content=content)
        ),
    )

    with pytest.raises(ValueError):
        SafeRemoteCoverDownloader().download("https://example.test/cover.png")


@pytest.mark.parametrize("content", [b"not-an-image", b""])
def test_cover_publication_rejects_missing_or_damaged_images(
    tmp_path: Path, content: bytes
) -> None:
    publication = FilesystemRecognizedCoverPublication(tmp_path)

    with pytest.raises(ValueError):
        publication.publish(
            scope=MetadataTargetScope.BOOK,
            target_id="book-1",
            content=content,
            previous_stored_path=None,
        )

    assert list(tmp_path.rglob("*.part")) == []


def test_cover_publication_revert_restores_the_original_file(tmp_path: Path) -> None:
    cover_root = tmp_path / "covers"
    cover_root.mkdir(parents=True)
    original_path = cover_root / "book-1.png"
    original_content = _image_bytes("PNG")
    original_path.write_bytes(original_content)
    publication = FilesystemRecognizedCoverPublication(tmp_path)

    published = publication.publish(
        scope=MetadataTargetScope.BOOK,
        target_id="book-1",
        content=_image_bytes("PNG"),
        previous_stored_path="covers/book-1.png",
    )
    publication.revert(published)

    assert original_path.read_bytes() == original_content
    assert list(cover_root.glob("*.backup")) == []
