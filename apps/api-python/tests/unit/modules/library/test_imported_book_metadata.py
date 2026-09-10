"""Book identification rejects stale writes and restores published artwork."""

from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from app.contracts.publication_metadata import PublicationMetadata
from app.modules.library.application.imported_book_metadata import (
    IdentifiedBookMetadata,
    IdentifyImportedBook,
    ImportedBookSnapshot,
)
from app.modules.library.infrastructure.source_node_cover import (
    FilesystemSourceNodeCoverPublication,
)


def _png(color: str) -> bytes:
    stream = BytesIO()
    Image.new("RGB", (2, 2), color).save(stream, format="PNG")
    return stream.getvalue()


class _Repository:
    def __init__(self, snapshot: ImportedBookSnapshot, stale: bool) -> None:
        self.snapshot = snapshot
        self.stale = stale
        self.title = "Original"

    def load(self, source_node_id: str) -> ImportedBookSnapshot:
        return self.snapshot

    def inspect(self, snapshot: ImportedBookSnapshot) -> IdentifiedBookMetadata:
        return IdentifiedBookMetadata(PublicationMetadata(title="New"), _png("blue"))

    def still_current(self, snapshot: ImportedBookSnapshot) -> bool:
        return not self.stale

    def apply(
        self,
        snapshot: ImportedBookSnapshot,
        result: IdentifiedBookMetadata,
        cover_path: str | None,
    ) -> None:
        self.title = result.metadata.title or ""


class _UnitOfWork:
    def __init__(self, repository: _Repository, fail_commit: bool) -> None:
        self.repository = repository
        self.fail_commit = fail_commit
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1
        if self.fail_commit and self.commits == 2:
            raise RuntimeError("commit failed")

    def rollback(self) -> None:
        self.repository.title = "Original"


@pytest.mark.parametrize("failure", ("stale", "publish", "commit"))
def test_failed_or_stale_identification_keeps_original_book_and_cover(
    tmp_path: Path, monkeypatch, failure: str
) -> None:
    covers = FilesystemSourceNodeCoverPublication(tmp_path)
    old = covers.prepare(source_node_id="root", content=_png("red"))
    published = covers.publish(old, previous_stored_path=None)
    covers.complete(published, previous_stored_path=None)
    snapshot = ImportedBookSnapshot(
        "book",
        "root",
        1,
        "[]",
        str(tmp_path),
        "Book",
        True,
        ("SIDECAR_OPF", "EMBEDDED", "PATH"),
        (),
        None,
        old.stored_path,
        False,
    )
    repository = _Repository(snapshot, stale=failure == "stale")
    unit_of_work = _UnitOfWork(repository, fail_commit=failure == "commit")
    if failure == "publish":
        from app.modules.library.infrastructure import source_node_cover

        replace = source_node_cover.os.replace

        def fail_temporary_publish(source, target):
            if str(source).endswith(".part"):
                raise OSError("publication failed")
            return replace(source, target)

        monkeypatch.setattr(source_node_cover.os, "replace", fail_temporary_publish)
    use_case = IdentifyImportedBook(repository, covers, unit_of_work)
    if failure == "stale":
        assert use_case.execute("root") == "stale"
    else:
        with pytest.raises((RuntimeError, OSError)):
            use_case.execute("root")
    assert repository.title == "Original"
    assert old.final_path.read_bytes() == _png("red")
    assert tuple(old.final_path.parent.iterdir()) == (old.final_path,)
