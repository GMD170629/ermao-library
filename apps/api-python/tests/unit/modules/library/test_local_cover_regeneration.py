from __future__ import annotations

from pathlib import Path

import pytest

from app.modules.library.application.local_cover_regeneration import (
    LocalCoverFailureCode,
    LocalCoverScope,
    LocalCoverUnavailableError,
    RegenerateLocalMetadataCovers,
    ResourceLocalMetadataSource,
)
from app.modules.library.application.resource_commands import (
    LibraryActor,
    ResourceContext,
)
from app.modules.library.application.resource_cover import (
    PreparedResourceCover,
    PublishedResourceCover,
)
from app.modules.library.application.source_node_commands import (
    PreparedSourceNodeCover,
    PublishedSourceNodeCover,
)


class _Access:
    def can_access_book(self, *, actor: LibraryActor, book_id: str) -> bool:
        del actor
        return book_id == "book"

    def get_resource_context(
        self, *, actor: LibraryActor, book_id: str, resource_id: str
    ) -> ResourceContext | None:
        del actor
        if book_id != "book" or resource_id not in {"r1", "r2", "r3"}:
            return None
        return ResourceContext(id=resource_id, book_id=book_id, sort_order=0)


class _Sources:
    def __init__(self, *, root: bool = True) -> None:
        self.root = root
        self.resource_paths = {"r1": "old-r1", "r2": "old-r2", "r3": None}
        self.source_path = "old-source"
        self.marked_resources: list[tuple[str, str]] = []
        self.marked_source: tuple[LocalCoverScope, str] | None = None

    def load_resource_source(
        self, *, book_id: str, resource_id: str
    ) -> ResourceLocalMetadataSource | None:
        if book_id != "book" or resource_id not in {"r1", "r2", "r3"}:
            return None
        return ResourceLocalMetadataSource(
            adapter_id="epub",
            source_format="EPUB",
            root_path=Path("/library"),
            resource_relative_path=f"{resource_id}.epub",
            asset_relative_paths=(f"{resource_id}.epub",),
            local_metadata_priority=("SIDECAR_OPF", "EMBEDDED", "PATH"),
        )

    def source_scope(
        self, *, book_id: str, source_node_id: str
    ) -> LocalCoverScope | None:
        if book_id != "book" or source_node_id != "node":
            return None
        return LocalCoverScope(
            book_id=book_id,
            source_node_id=source_node_id,
            resource_ids=("r1", "r2", "r3"),
            is_book_root=self.root,
        )

    def book_scope(self, *, book_id: str) -> LocalCoverScope | None:
        return self.source_scope(book_id=book_id, source_node_id="node")

    def current_resource_cover_path(self, resource_id: str) -> str | None:
        return self.resource_paths[resource_id]

    def current_source_cover_path(self, source_node_id: str) -> str | None:
        assert source_node_id == "node"
        return self.source_path

    def mark_resource_cover_ready(self, *, resource_id: str, cover_path: str) -> None:
        self.resource_paths[resource_id] = cover_path
        self.marked_resources.append((resource_id, cover_path))

    def mark_source_cover_ready(
        self, *, scope: LocalCoverScope, cover_path: str
    ) -> None:
        self.source_path = cover_path
        self.marked_source = (scope, cover_path)


class _Parser:
    def __init__(self, results: dict[str, bytes | LocalCoverFailureCode]) -> None:
        self.results = results
        self.calls: list[str] = []

    def extract_cover(
        self, source: ResourceLocalMetadataSource
    ) -> bytes | LocalCoverFailureCode:
        resource_id = Path(source.resource_relative_path).stem
        self.calls.append(resource_id)
        return self.results[resource_id]


class _ResourceCovers:
    def __init__(self) -> None:
        self.contents: dict[str, bytes] = {}
        self.completed: list[str] = []
        self.reverted: list[str] = []

    def prepare(self, *, resource_id: str, content: bytes) -> PreparedResourceCover:
        self.contents[resource_id] = content
        root = Path("/tmp")
        return PreparedResourceCover(
            temporary_path=root / f"{resource_id}.part",
            final_path=root / f"{resource_id}.png",
            stored_path=f"covers/resources/{resource_id}.png",
        )

    def publish(
        self,
        prepared: PreparedResourceCover,
        *,
        previous_stored_path: str | None,
    ) -> PublishedResourceCover:
        del previous_stored_path
        return PublishedResourceCover(prepared=prepared, backup_path=None)

    def revert(self, published: PublishedResourceCover) -> None:
        resource_id = published.prepared.final_path.stem
        self.contents.pop(resource_id, None)
        self.reverted.append(resource_id)

    def complete(
        self,
        published: PublishedResourceCover,
        *,
        previous_stored_path: str | None,
    ) -> None:
        del previous_stored_path
        self.completed.append(published.prepared.final_path.stem)


class _SourceCovers:
    def __init__(self) -> None:
        self.content: bytes | None = None

    def prepare(
        self, *, source_node_id: str, content: bytes
    ) -> PreparedSourceNodeCover:
        self.content = content
        root = Path("/tmp")
        return PreparedSourceNodeCover(
            temporary_path=root / f"{source_node_id}.part",
            final_path=root / f"{source_node_id}.png",
            stored_path=f"covers/source-nodes/{source_node_id}.png",
        )

    def publish(
        self,
        prepared: PreparedSourceNodeCover,
        *,
        previous_stored_path: str | None,
    ) -> PublishedSourceNodeCover:
        del previous_stored_path
        return PublishedSourceNodeCover(prepared=prepared, backup_path=None)

    def revert(self, published: PublishedSourceNodeCover) -> None:
        del published

    def complete(
        self,
        published: PublishedSourceNodeCover,
        *,
        previous_stored_path: str | None,
    ) -> None:
        del published, previous_stored_path

    def remove(self, stored_path: str) -> None:
        del stored_path


class _UnitOfWork:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class _FailingCommitUnitOfWork(_UnitOfWork):
    def commit(self) -> None:
        raise RuntimeError("commit failed")


def _actor() -> LibraryActor:
    return LibraryActor(
        user_id="admin",
        can_manage_system=True,
        is_admin=True,
        can_view_manual_imports=True,
        library_ids=(),
    )


def _use_case(
    sources: _Sources,
    parser: _Parser,
) -> tuple[RegenerateLocalMetadataCovers, _ResourceCovers, _SourceCovers, _UnitOfWork]:
    resource_covers = _ResourceCovers()
    source_covers = _SourceCovers()
    unit_of_work = _UnitOfWork()
    return (
        RegenerateLocalMetadataCovers(
            access=_Access(),
            sources=sources,
            parser=parser,
            resource_covers=resource_covers,
            source_covers=source_covers,
            unit_of_work=unit_of_work,
        ),
        resource_covers,
        source_covers,
        unit_of_work,
    )


def test_resource_regeneration_updates_only_the_selected_resource() -> None:
    sources = _Sources()
    use_case, resource_covers, source_covers, unit_of_work = _use_case(
        sources,
        _Parser({"r1": b"new-cover"}),
    )

    result = use_case.regenerate_resource(
        actor=_actor(), book_id="book", resource_id="r1"
    )

    assert result.updated_resource_ids == ("r1",)
    assert sources.marked_resources == [("r1", "covers/resources/r1.png")]
    assert sources.marked_source is None
    assert resource_covers.contents == {"r1": b"new-cover"}
    assert source_covers.content is None
    assert unit_of_work.commits == 1


def test_resource_failure_preserves_the_existing_cover() -> None:
    sources = _Sources()
    use_case, resource_covers, _source_covers, unit_of_work = _use_case(
        sources,
        _Parser({"r1": "LOCAL_COVER_NOT_FOUND"}),
    )

    with pytest.raises(LocalCoverUnavailableError) as raised:
        use_case.regenerate_resource(actor=_actor(), book_id="book", resource_id="r1")

    assert raised.value.code == "LOCAL_COVER_NOT_FOUND"
    assert sources.resource_paths["r1"] == "old-r1"
    assert sources.marked_resources == []
    assert resource_covers.contents == {}
    assert unit_of_work.commits == 0


def test_resource_commit_failure_reverts_the_published_cover() -> None:
    sources = _Sources()
    parser = _Parser({"r1": b"new-cover"})
    resource_covers = _ResourceCovers()
    source_covers = _SourceCovers()
    unit_of_work = _FailingCommitUnitOfWork()
    use_case = RegenerateLocalMetadataCovers(
        access=_Access(),
        sources=sources,
        parser=parser,
        resource_covers=resource_covers,
        source_covers=source_covers,
        unit_of_work=unit_of_work,
    )

    with pytest.raises(RuntimeError, match="commit failed"):
        use_case.regenerate_resource(
            actor=_actor(),
            book_id="book",
            resource_id="r1",
        )

    assert resource_covers.reverted == ["r1"]
    assert resource_covers.completed == []
    assert resource_covers.contents == {}


def test_directory_updates_every_successful_resource_and_uses_first_cover() -> None:
    sources = _Sources(root=True)
    parser = _Parser(
        {
            "r1": b"first",
            "r2": "LOCAL_METADATA_SOURCE_UNAVAILABLE",
            "r3": b"third",
        }
    )
    use_case, _resource_covers, source_covers, unit_of_work = _use_case(sources, parser)

    result = use_case.regenerate_source_node(
        actor=_actor(), book_id="book", source_node_id="node"
    )

    assert parser.calls == ["r1", "r2", "r3"]
    assert result.updated_resource_ids == ("r1", "r3")
    assert [(item.resource_id, item.reason) for item in result.skipped] == [
        ("r2", "LOCAL_METADATA_SOURCE_UNAVAILABLE")
    ]
    assert result.source_node_updated is True
    assert result.book_updated is True
    assert source_covers.content == b"first"
    assert sources.resource_paths["r2"] == "old-r2"
    assert unit_of_work.commits == 3


def test_non_root_directory_does_not_report_a_book_cover_update() -> None:
    sources = _Sources(root=False)
    use_case, _resource_covers, _source_covers, _unit_of_work = _use_case(
        sources,
        _Parser(
            {
                "r1": b"one",
                "r2": b"two",
                "r3": b"three",
            }
        ),
    )

    result = use_case.regenerate_source_node(
        actor=_actor(), book_id="book", source_node_id="node"
    )

    assert result.source_node_updated is True
    assert result.book_updated is False
