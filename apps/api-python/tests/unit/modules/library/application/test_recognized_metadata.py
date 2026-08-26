from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from app.modules.library.application.recognized_metadata import (
    ApplyRecognizedMetadata,
    ApplyRecognizedMetadataCommand,
    BookMetadataChanges,
    BookMetadataState,
    InvalidRecognizedMetadataError,
    MetadataTargetScope,
    RecognizedMetadataAuthorizationError,
    RecognizedMetadataCandidate,
    RecognizedMetadataField,
    RecognizedMetadataTargetState,
    RecognizedResourceChanges,
    ResourceMetadataState,
)
from app.modules.library.application.resource_commands import LibraryActor


def _actor(*, manager: bool = True) -> LibraryActor:
    return LibraryActor(
        user_id="user-1",
        can_manage_system=manager,
        is_admin=manager,
        can_view_manual_imports=manager,
        library_ids=("library-1",),
    )


def _state(*, resource: bool = False) -> RecognizedMetadataTargetState:
    return RecognizedMetadataTargetState(
        book=BookMetadataState(
            title="旧标题",
            author="旧作者",
            description=None,
            series_name="系列",
            series_index=1,
            tags=("旧标签",),
        ),
        resource=(
            ResourceMetadataState(
                title="第一卷",
                description=None,
                publisher=None,
                published_at=None,
                language=None,
                isbn=None,
                identifier=None,
                narrator=None,
                abridged=None,
                resource_index=1,
            )
            if resource
            else None
        ),
    )


@dataclass
class FakePort:
    state: RecognizedMetadataTargetState | None
    calls: list[
        tuple[
            str,
            str | None,
            BookMetadataChanges,
            RecognizedResourceChanges,
            tuple[str, ...] | None,
        ]
    ] = field(default_factory=list)

    def load_target(
        self,
        *,
        actor: LibraryActor,
        book_id: str,
        resource_id: str | None,
    ) -> RecognizedMetadataTargetState | None:
        del actor, book_id, resource_id
        return self.state

    def apply_changes(
        self,
        *,
        book_id: str,
        resource_id: str | None,
        book_changes: BookMetadataChanges,
        resource_changes: RecognizedResourceChanges,
        tags: tuple[str, ...] | None,
        now: datetime,
    ) -> None:
        del now
        self.calls.append((book_id, resource_id, book_changes, resource_changes, tags))


@dataclass
class FakeUnitOfWork:
    commits: int = 0
    rollbacks: int = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


@dataclass
class FakeCovers:
    should_fail: bool = False
    calls: list[tuple[str, str | None, MetadataTargetScope, str]] = field(
        default_factory=list
    )

    def apply(
        self,
        *,
        actor: LibraryActor,
        book_id: str,
        resource_id: str | None,
        scope: MetadataTargetScope,
        cover_url: str,
        now: datetime,
    ) -> None:
        del actor, now
        self.calls.append((book_id, resource_id, scope, cover_url))
        if self.should_fail:
            raise ValueError("cover failed")


def _command(
    *,
    scope: MetadataTargetScope,
    fields: tuple[RecognizedMetadataField, ...],
    candidate: RecognizedMetadataCandidate,
    actor: LibraryActor | None = None,
) -> ApplyRecognizedMetadataCommand:
    return ApplyRecognizedMetadataCommand(
        actor=actor or _actor(),
        book_id="book-1",
        scope=scope,
        resource_id="resource-1" if scope is MetadataTargetScope.RESOURCE else None,
        candidate=candidate,
        fields=fields,
        now=datetime(2026, 8, 26, tzinfo=UTC),
    )


def test_book_apply_normalizes_tags_and_only_writes_changed_selected_fields() -> None:
    port = FakePort(_state())
    unit_of_work = FakeUnitOfWork()
    covers = FakeCovers()
    use_case = ApplyRecognizedMetadata(port, unit_of_work, covers)

    result = use_case.execute(
        _command(
            scope=MetadataTargetScope.BOOK,
            candidate=RecognizedMetadataCandidate(
                id="candidate-1",
                source="douban",
                title=" 旧标题 ",
                author=" 新作者 ",
                tags=(" 科幻 ", "科幻", "Manga"),
            ),
            fields=(
                RecognizedMetadataField.BOOK_TITLE,
                RecognizedMetadataField.BOOK_AUTHOR,
                RecognizedMetadataField.BOOK_TAGS,
            ),
        )
    )

    assert result.applied_fields == (
        RecognizedMetadataField.BOOK_AUTHOR,
        RecognizedMetadataField.BOOK_TAGS,
    )
    assert result.skipped_fields == (RecognizedMetadataField.BOOK_TITLE,)
    assert result.cover_status == "notSelected"
    assert port.calls == [
        (
            "book-1",
            None,
            {"author": "新作者"},
            {},
            ("科幻", "Manga"),
        )
    ]
    assert unit_of_work.commits == 1
    assert unit_of_work.rollbacks == 0


def test_resource_apply_updates_book_and_resource_before_isolated_cover_failure() -> (
    None
):
    port = FakePort(_state(resource=True))
    unit_of_work = FakeUnitOfWork()
    covers = FakeCovers(should_fail=True)
    use_case = ApplyRecognizedMetadata(port, unit_of_work, covers)

    result = use_case.execute(
        _command(
            scope=MetadataTargetScope.RESOURCE,
            candidate=RecognizedMetadataCandidate(
                id="candidate-2",
                source="bangumi",
                author="新作者",
                publisher="出版社",
                abridged=False,
                cover_url="https://example.test/cover.png",
            ),
            fields=(
                RecognizedMetadataField.BOOK_AUTHOR,
                RecognizedMetadataField.RESOURCE_PUBLISHER,
                RecognizedMetadataField.RESOURCE_ABRIDGED,
                RecognizedMetadataField.RESOURCE_COVER,
            ),
        )
    )

    assert result.applied_fields == (
        RecognizedMetadataField.BOOK_AUTHOR,
        RecognizedMetadataField.RESOURCE_PUBLISHER,
        RecognizedMetadataField.RESOURCE_ABRIDGED,
    )
    assert result.cover_status == "failed"
    assert port.calls == [
        (
            "book-1",
            "resource-1",
            {"author": "新作者"},
            {"publisher": "出版社", "abridged": False},
            None,
        )
    ]
    assert unit_of_work.commits == 1
    assert covers.calls == [
        (
            "book-1",
            "resource-1",
            MetadataTargetScope.RESOURCE,
            "https://example.test/cover.png",
        )
    ]


@pytest.mark.parametrize(
    "command",
    [
        _command(
            scope=MetadataTargetScope.BOOK,
            candidate=RecognizedMetadataCandidate(id="c", source="douban"),
            fields=(RecognizedMetadataField.BOOK_AUTHOR,),
        ),
        _command(
            scope=MetadataTargetScope.BOOK,
            candidate=RecognizedMetadataCandidate(
                id="c", source="douban", publisher="出版社"
            ),
            fields=(RecognizedMetadataField.RESOURCE_PUBLISHER,),
        ),
        _command(
            scope=MetadataTargetScope.BOOK,
            candidate=RecognizedMetadataCandidate(
                id="c", source="douban", author="作者"
            ),
            fields=(
                RecognizedMetadataField.BOOK_AUTHOR,
                RecognizedMetadataField.BOOK_AUTHOR,
            ),
        ),
    ],
)
def test_invalid_or_unavailable_selected_fields_are_rejected(
    command: ApplyRecognizedMetadataCommand,
) -> None:
    use_case = ApplyRecognizedMetadata(
        FakePort(_state()), FakeUnitOfWork(), FakeCovers()
    )

    with pytest.raises(InvalidRecognizedMetadataError):
        use_case.execute(command)


def test_only_system_managers_may_apply_recognized_metadata() -> None:
    use_case = ApplyRecognizedMetadata(
        FakePort(_state()), FakeUnitOfWork(), FakeCovers()
    )

    with pytest.raises(RecognizedMetadataAuthorizationError):
        use_case.execute(
            _command(
                scope=MetadataTargetScope.BOOK,
                candidate=RecognizedMetadataCandidate(
                    id="c", source="douban", author="作者"
                ),
                fields=(RecognizedMetadataField.BOOK_AUTHOR,),
                actor=_actor(manager=False),
            )
        )
