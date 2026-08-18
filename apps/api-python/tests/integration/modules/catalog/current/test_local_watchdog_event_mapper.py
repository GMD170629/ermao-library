from __future__ import annotations

import os
import unicodedata
from pathlib import Path

import pytest
from watchdog.events import (
    DirCreatedEvent,
    DirDeletedEvent,
    DirModifiedEvent,
    DirMovedEvent,
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileMovedEvent,
    FileSystemEvent,
)

from app.modules.catalog.domain.watcher import (
    WatcherEntryHint,
    WatcherMovedEntryType,
    WatcherMoveEvent,
    WatcherPathEvent,
    WatcherPathEventKind,
    WatcherTrustLost,
    WatcherTrustLostReason,
)
from app.modules.catalog.infrastructure.watcher import LocalWatchdogEventMapper
from app.modules.catalog.infrastructure.watcher import (
    watchdog_event_mapper as mapper_module,
)


def _mapper(root: Path) -> LocalWatchdogEventMapper:
    return LocalWatchdogEventMapper(str(root.resolve()))


@pytest.mark.parametrize(
    ("event_factory", "kind", "entry_hint", "relative_path"),
    [
        (
            FileCreatedEvent,
            WatcherPathEventKind.CREATE,
            WatcherEntryHint.FILE,
            ("a.epub",),
        ),
        (
            FileModifiedEvent,
            WatcherPathEventKind.MODIFY,
            WatcherEntryHint.FILE,
            ("Shelf", "a.epub"),
        ),
        (
            FileDeletedEvent,
            WatcherPathEventKind.DELETE,
            WatcherEntryHint.FILE,
            ("a.epub",),
        ),
        (
            DirCreatedEvent,
            WatcherPathEventKind.CREATE,
            WatcherEntryHint.DIRECTORY,
            ("Shelf",),
        ),
        (
            DirDeletedEvent,
            WatcherPathEventKind.DELETE,
            WatcherEntryHint.DIRECTORY,
            ("Shelf",),
        ),
    ],
)
def test_mapper_converts_trusted_child_events_without_filesystem_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    event_factory: type[FileSystemEvent],
    kind: WatcherPathEventKind,
    entry_hint: WatcherEntryHint,
    relative_path: tuple[str, ...],
) -> None:
    mapper = _mapper(tmp_path)
    event_path = tmp_path.joinpath(*relative_path)

    def unexpected_filesystem_access(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("watcher mapping must remain lexical")

    monkeypatch.setattr(mapper_module.os, "stat", unexpected_filesystem_access)
    monkeypatch.setattr(mapper_module.os, "open", unexpected_filesystem_access)

    assert mapper.map(event_factory(str(event_path))) == WatcherPathEvent(
        kind=kind,
        relative_path=relative_path,
        entry_hint=entry_hint,
    )


@pytest.mark.parametrize(
    ("event_factory", "entry_type"),
    [
        (FileMovedEvent, WatcherMovedEntryType.FILE),
        (DirMovedEvent, WatcherMovedEntryType.DIRECTORY),
    ],
)
def test_mapper_preserves_a_trusted_inside_move_pair_without_identity_guessing(
    tmp_path: Path,
    event_factory: type[FileSystemEvent],
    entry_type: WatcherMovedEntryType,
) -> None:
    mapper = _mapper(tmp_path)

    mapped = mapper.map(
        event_factory(
            str(tmp_path / "Old" / "book.epub"),
            str(tmp_path / "New" / "book.epub"),
        )
    )

    assert mapped == WatcherMoveEvent(
        source_path=("Old", "book.epub"),
        destination_path=("New", "book.epub"),
        entry_type=entry_type,
    )
    assert not hasattr(mapped, "filesystem_identity")


def test_parent_directory_move_subsumes_watchdog_synthetic_descendant_moves(
    tmp_path: Path,
) -> None:
    mapper = _mapper(tmp_path)
    events = (
        DirMovedEvent(str(tmp_path / "Old"), str(tmp_path / "New")),
        DirMovedEvent(
            str(tmp_path / "Old" / "Volume"),
            str(tmp_path / "New" / "Volume"),
            is_synthetic=True,
        ),
        FileMovedEvent(
            str(tmp_path / "Old" / "Volume" / "book.epub"),
            str(tmp_path / "New" / "Volume" / "book.epub"),
            is_synthetic=True,
        ),
    )

    mapped = tuple(
        event for raw_event in events if (event := mapper.map(raw_event)) is not None
    )

    assert mapped == (
        WatcherMoveEvent(
            source_path=("Old",),
            destination_path=("New",),
            entry_type=WatcherMovedEntryType.DIRECTORY,
        ),
    )


def test_synthetic_root_move_is_never_elided_as_a_child_expansion(
    tmp_path: Path,
) -> None:
    mapper = _mapper(tmp_path)

    mapped = mapper.map(
        DirMovedEvent(
            str(tmp_path),
            str(tmp_path.parent / f"{tmp_path.name}-moved"),
            is_synthetic=True,
        )
    )

    assert mapped == WatcherTrustLost(WatcherTrustLostReason.UNTRUSTED)


def test_mapper_degrades_cross_boundary_moves_to_the_observable_inside_side(
    tmp_path: Path,
) -> None:
    mapper = _mapper(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-outside" / "book.epub"

    leaving = mapper.map(FileMovedEvent(str(tmp_path / "book.epub"), str(outside)))
    arriving = mapper.map(FileMovedEvent(str(outside), str(tmp_path / "book.epub")))

    assert leaving == WatcherPathEvent(
        kind=WatcherPathEventKind.DELETE,
        relative_path=("book.epub",),
        entry_hint=WatcherEntryHint.FILE,
    )
    assert arriving == WatcherPathEvent(
        kind=WatcherPathEventKind.CREATE,
        relative_path=("book.epub",),
        entry_hint=WatcherEntryHint.FILE,
    )


def test_mapper_ignores_only_redundant_root_directory_modify(
    tmp_path: Path,
) -> None:
    mapper = _mapper(tmp_path)
    child = mapper.map(FileCreatedEvent(str(tmp_path / "book.epub")))
    redundant_root_modify = mapper.map(DirModifiedEvent(str(tmp_path)))

    assert [event for event in (child, redundant_root_modify) if event is not None] == [
        WatcherPathEvent(
            kind=WatcherPathEventKind.CREATE,
            relative_path=("book.epub",),
            entry_hint=WatcherEntryHint.FILE,
        )
    ]


@pytest.mark.parametrize(
    "event_factory",
    [DirDeletedEvent, lambda root: DirMovedEvent(root, f"{root}-moved")],
)
def test_root_delete_or_move_reports_root_binding_loss(
    tmp_path: Path,
    event_factory: object,
) -> None:
    mapper = _mapper(tmp_path)
    assert callable(event_factory)
    event = event_factory(str(tmp_path))

    assert mapper.map(event) == WatcherTrustLost(
        WatcherTrustLostReason.ROOT_BINDING_LOST
    )


@pytest.mark.parametrize(
    "event",
    [
        pytest.param(lambda root: DirCreatedEvent(root), id="root-create"),
        pytest.param(
            lambda root: FileCreatedEvent(f"{root}/book.epub", is_synthetic=True),
            id="synthetic",
        ),
        pytest.param(
            lambda root: FileCreatedEvent(
                f"{root}/book.epub", is_synthetic="not-a-boolean"
            ),
            id="malformed-synthetic-flag",
        ),
        pytest.param(lambda root: FileSystemEvent(f"{root}/book.epub"), id="unknown"),
        pytest.param(
            lambda root: FileMovedEvent(
                f"{root}-outside/a.epub", f"{root}-outside/b.epub"
            ),
            id="outside-move",
        ),
    ],
)
def test_untrusted_notifications_fail_closed(
    tmp_path: Path,
    event: object,
) -> None:
    mapper = _mapper(tmp_path)
    assert callable(event)

    assert mapper.map(event(str(tmp_path))) == WatcherTrustLost(
        WatcherTrustLostReason.UNTRUSTED
    )


@pytest.mark.parametrize(
    "event_path",
    [
        "relative/book.epub",
        "/tmp/library/../library/book.epub",
        "/tmp/library//book.epub",
        "/tmp/library/book\x00.epub",
        "/tmp/library/invalid-\udcff.epub",
        b"/tmp/library/invalid-\xff.epub",
    ],
)
def test_malformed_paths_fail_closed_without_leaking_them(
    event_path: bytes | str,
) -> None:
    mapper = LocalWatchdogEventMapper("/tmp/library")

    mapped = mapper.map(FileCreatedEvent(event_path))

    assert mapped == WatcherTrustLost(WatcherTrustLostReason.UNTRUSTED)
    assert "/tmp/library" not in repr(mapped)
    assert "invalid" not in repr(mapped)


def test_prefix_trap_is_outside_the_root_and_fails_closed() -> None:
    mapper = LocalWatchdogEventMapper("/tmp/library")

    mapped = mapper.map(FileCreatedEvent("/tmp/library-copy/book.epub"))

    assert mapped == WatcherTrustLost(WatcherTrustLostReason.UNTRUSTED)


def test_mapper_preserves_nfd_and_nfc_sibling_spelling() -> None:
    mapper = LocalWatchdogEventMapper("/tmp/library")
    nfd_name = unicodedata.normalize("NFD", "café.epub")
    nfc_name = unicodedata.normalize("NFC", "café.epub")

    nfd = mapper.map(FileCreatedEvent(f"/tmp/library/{nfd_name}"))
    nfc = mapper.map(FileCreatedEvent(f"/tmp/library/{nfc_name}"))

    assert isinstance(nfd, WatcherPathEvent)
    assert isinstance(nfc, WatcherPathEvent)
    assert nfd.relative_path == (nfd_name,)
    assert nfc.relative_path == (nfc_name,)
    assert nfd.relative_path != nfc.relative_path


def test_invalid_root_configuration_error_is_stable_and_path_free() -> None:
    with pytest.raises(ValueError) as caught:
        LocalWatchdogEventMapper("relative/private/library")

    assert (
        str(caught.value) == "canonical_root must be an absolute normalized host path"
    )
    assert "private" not in str(caught.value)


def test_utf8_byte_event_path_maps_without_rewriting_host_spelling() -> None:
    mapper = LocalWatchdogEventMapper("/tmp/library")
    raw_name = unicodedata.normalize("NFD", "café.epub")

    mapped = mapper.map(FileCreatedEvent(os.fsencode(f"/tmp/library/{raw_name}")))

    assert isinstance(mapped, WatcherPathEvent)
    assert mapped.relative_path == (raw_name,)
