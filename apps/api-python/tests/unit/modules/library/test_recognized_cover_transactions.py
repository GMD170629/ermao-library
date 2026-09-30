"""Remote cover I/O stays outside database transactions and stale writes revert."""

from datetime import UTC, datetime

import pytest

from app.modules.library.application.recognized_metadata import (
    ApplyRecognizedCover,
    InvalidRecognizedMetadataError,
    MetadataTargetScope,
    PublishedRecognizedCover,
    RecognizedCoverState,
)
from app.modules.library.application.resource_commands import LibraryActor


def test_remote_cover_rechecks_state_after_publish_and_reverts_stale_file(tmp_path):
    active = False
    reverted = False
    checks = 0
    original = RecognizedCoverState("book", "old.png")

    class Metadata:
        def load_cover_state(self, **kwargs):
            nonlocal active, checks
            active = True
            checks += 1
            return original if checks < 3 else RecognizedCoverState("book", "changed.png")

        def mark_cover_ready(self, **kwargs):
            raise AssertionError("A stale cover must not be written")

    class Downloader:
        def download(self, url):
            assert not active
            return b"image"

    class Publication:
        def publish(self, **kwargs):
            assert not active
            return PublishedRecognizedCover("book", "new.png", tmp_path / "new.png", None)

        def revert(self, published):
            nonlocal reverted
            assert not active
            reverted = True

    class UnitOfWork:
        def rollback(self):
            nonlocal active
            active = False

        def commit(self):
            raise AssertionError("A stale cover must not commit")

    use_case = ApplyRecognizedCover(Metadata(), Downloader(), Publication(), UnitOfWork())
    with pytest.raises(InvalidRecognizedMetadataError, match="METADATA_CHANGED"):
        use_case.apply(
            actor=LibraryActor("user", True, True, True, ("library",)),
            book_id="book",
            resource_id=None,
            scope=MetadataTargetScope.BOOK,
            cover_url="https://example.invalid/cover.png",
            now=datetime.now(UTC),
        )
    assert checks == 3
    assert reverted
