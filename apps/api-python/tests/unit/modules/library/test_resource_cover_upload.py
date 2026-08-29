from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.modules.library.application.resource_commands import (
    LibraryActor,
    ResourceContext,
    ResourceMetadataChanges,
)
from app.modules.library.application.resource_cover import (
    PreparedResourceCover,
    PublishedResourceCover,
    ResourceCoverContext,
    UploadResourceCover,
    UploadResourceCoverCommand,
)


class FakeAccess:
    def can_access_book(self, *, actor: LibraryActor, book_id: str) -> bool:
        return actor.can_manage_system and book_id == "book-1"

    def get_resource_context(
        self, *, actor: LibraryActor, book_id: str, resource_id: str
    ) -> ResourceContext | None:
        if not self.can_access_book(actor=actor, book_id=book_id):
            return None
        return ResourceContext(id=resource_id, book_id=book_id, sort_order=1)

    def get_resource_contexts(
        self,
        *,
        actor: LibraryActor,
        book_id: str,
        resource_ids: tuple[str, ...],
    ) -> tuple[ResourceContext, ...]:
        return tuple(
            context
            for resource_id in resource_ids
            if (
                context := self.get_resource_context(
                    actor=actor, book_id=book_id, resource_id=resource_id
                )
            )
            is not None
        )

    def update_resource(
        self,
        *,
        resource_id: str,
        changes: ResourceMetadataChanges,
        now: datetime,
    ) -> None:
        del resource_id, changes, now
        raise AssertionError("metadata mutation is not part of cover upload")


class FakeCoverState:
    ready_path: str | None = None

    def current_cover_path(self, *, resource_id: str) -> str | None:
        assert resource_id == "resource-1"
        return "covers/resources/old.png"

    def mark_ready(self, *, resource_id: str, cover_path: str, now: datetime) -> None:
        del now
        assert resource_id == "resource-1"
        self.ready_path = cover_path

    def get_context(
        self, *, book_id: str, resource_id: str
    ) -> ResourceCoverContext | None:
        del book_id, resource_id
        return None

    def mark_pending(self, *, resource_id: str, now: datetime) -> None:
        del resource_id, now
        raise AssertionError("regeneration is not part of cover upload")


class FakePublication:
    reverted = False
    completed = False

    def prepare(self, *, resource_id: str, content: bytes) -> PreparedResourceCover:
        assert (resource_id, content) == ("resource-1", b"cover")
        return PreparedResourceCover(
            temporary_path=Path("temporary"),
            final_path=Path("final"),
            stored_path="covers/resources/resource-1.png",
        )

    def publish(
        self, prepared: PreparedResourceCover, *, previous_stored_path: str | None
    ) -> PublishedResourceCover:
        assert previous_stored_path == "covers/resources/old.png"
        return PublishedResourceCover(prepared=prepared, backup_path=Path("backup"))

    def revert(self, published: PublishedResourceCover) -> None:
        assert published.prepared.stored_path == "covers/resources/resource-1.png"
        self.reverted = True

    def complete(
        self,
        published: PublishedResourceCover,
        *,
        previous_stored_path: str | None,
    ) -> None:
        del published, previous_stored_path
        self.completed = True


class FailingUnitOfWork:
    rolled_back = False

    def commit(self) -> None:
        raise RuntimeError("commit failed")

    def rollback(self) -> None:
        self.rolled_back = True


def test_upload_resource_cover_reverts_publication_when_commit_fails() -> None:
    covers = FakeCoverState()
    publication = FakePublication()
    unit_of_work = FailingUnitOfWork()
    use_case = UploadResourceCover(FakeAccess(), covers, publication, unit_of_work)

    with pytest.raises(RuntimeError, match="commit failed"):
        use_case.execute(
            UploadResourceCoverCommand(
                actor=LibraryActor(
                    user_id="admin",
                    can_manage_system=True,
                    is_admin=True,
                    can_view_manual_imports=True,
                    library_ids=(),
                ),
                book_id="book-1",
                resource_id="resource-1",
                content=b"cover",
                now=datetime.now(UTC),
            )
        )

    assert covers.ready_path == "covers/resources/resource-1.png"
    assert unit_of_work.rolled_back is True
    assert publication.reverted is True
    assert publication.completed is False
