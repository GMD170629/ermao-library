from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from app.modules.library.application.commands.manage_source_tree import (
    ChangeLibraryOrganizationMode,
    DeleteSourceNode,
    DisableReadableResource,
    EnableReadableResource,
    RelocateLibraryRoot,
)
from app.modules.library.domain.organization_modes import TargetLibraryOrganizationMode
from app.modules.library.domain.readable_resource_states import ResourceEnablementState


@dataclass
class NodeView:
    library_id: str


@dataclass
class ResourceView:
    library_id: str


class RecordingUoW:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.in_transaction = False

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self.in_transaction = True
        self.events.append("begin")
        try:
            yield
            self.events.append("commit")
        finally:
            self.in_transaction = False

    def release_before_io(self) -> None:
        self.events.append("release")
        self.in_transaction = False

    def rollback(self) -> None:
        self.events.append("rollback")


class FakeSourceNodes:
    def __init__(self) -> None:
        self.deleted: list[str] = []
        self.deleted_batches: list[tuple[str, ...]] = []
        self.nodes = {"node-1": NodeView(library_id="lib-1")}

    def get(self, source_node_id: str) -> NodeView | None:
        return self.nodes.get(source_node_id)

    def list_subtree_ids(self, source_node_id: str) -> tuple[str, ...]:
        return (source_node_id, f"{source_node_id}-child")

    def delete_subtree(self, source_node_id: str) -> None:
        self.deleted.append(source_node_id)

    def delete_nodes(self, source_node_ids: object) -> None:
        self.deleted_batches.append(tuple(source_node_ids))  # type: ignore[arg-type]


class FakeBooks:
    def __init__(self) -> None:
        self.resources = {"res-1": ResourceView(library_id="lib-1")}
        self.enablements: list[tuple[str, ResourceEnablementState]] = []
        self.deleted_overlay: list[str] = []
        self.deleted_assets: list[tuple[str, ...]] = []
        self.reevaluated: list[tuple[str, ...]] = []

    def get_resource(self, resource_id: str) -> ResourceView | None:
        return self.resources.get(resource_id)

    def set_enablement(self, resource_id: str, state: ResourceEnablementState) -> None:
        self.enablements.append((resource_id, state))

    def delete_library_overlay_rows(self, library_id: str) -> None:
        self.deleted_overlay.append(library_id)

    def delete_assets_for_source_nodes(
        self, source_node_ids: object
    ) -> tuple[str, ...]:
        ids = tuple(source_node_ids)  # type: ignore[arg-type]
        self.deleted_assets.append(ids)
        return ("res-1",)

    def reevaluate_ready_after_asset_loss(self, resource_ids: object) -> None:
        self.reevaluated.append(tuple(resource_ids))  # type: ignore[arg-type]


class FakeLibraries:
    def __init__(self) -> None:
        self.modes: list[tuple[str, TargetLibraryOrganizationMode]] = []
        self.roots: list[tuple[str, Path]] = []
        self.conflict = False

    def update_organization_mode(
        self, library_id: str, mode: TargetLibraryOrganizationMode
    ) -> None:
        self.modes.append((library_id, mode))

    def update_root_path(self, library_id: str, root_path: Path) -> None:
        self.roots.append((library_id, root_path))

    def root_path_conflicts(self, root_path: Path, *, exclude_library_id: str) -> bool:
        return self.conflict


class FakeFilesystem:
    def __init__(self, *, readable: bool = True) -> None:
        self.readable = readable
        self.checked: list[Path] = []

    def path_is_readable_directory(self, path: Path) -> bool:
        self.checked.append(path)
        return self.readable


class FakeLog:
    def __init__(self) -> None:
        self.events: list[str] = []

    def emit(self, event: str, **kwargs: object) -> None:
        self.events.append(event)


class FakeImportTasks:
    def __init__(self) -> None:
        self.fresh_scans: list[str] = []
        self.deleted_for_nodes: list[tuple[str, ...]] = []

    def replace_with_fresh_library_scan(self, library_id: str) -> None:
        self.fresh_scans.append(library_id)

    def delete_tasks_for_source_nodes(self, source_node_ids: object) -> None:
        self.deleted_for_nodes.append(tuple(source_node_ids))


def test_delete_source_node_cleans_subtree_and_assets() -> None:
    nodes = FakeSourceNodes()
    books = FakeBooks()
    import_tasks = FakeImportTasks()
    uow = RecordingUoW()
    log = FakeLog()
    result = DeleteSourceNode(
        source_nodes=nodes,
        books_resources=books,
        import_tasks=import_tasks,
        uow=uow,
        log=log,
    ).execute("node-1")
    assert result.ok is True
    assert nodes.deleted == []
    assert nodes.deleted_batches == [("node-1-child",), ("node-1",)]
    assert books.deleted_assets == [("node-1", "node-1-child")]
    assert import_tasks.deleted_for_nodes == [("node-1", "node-1-child")]
    assert books.reevaluated == [("res-1",)]
    assert "source_tree.delete.completed" in log.events
    assert uow.events == [
        "begin",
        "commit",
        "begin",
        "commit",
        "begin",
        "commit",
        "begin",
        "commit",
        "begin",
        "commit",
    ]


def test_delete_source_node_commits_cleanup_in_bounded_batches() -> None:
    nodes = FakeSourceNodes()
    books = FakeBooks()
    import_tasks = FakeImportTasks()
    uow = RecordingUoW()

    result = DeleteSourceNode(
        source_nodes=nodes,
        books_resources=books,
        import_tasks=import_tasks,
        uow=uow,
        log=FakeLog(),
        asset_cleanup_batch_size=1,
        task_batch_size=1,
        source_node_batch_size=1,
    ).execute("node-1")

    assert result.ok is True
    assert books.deleted_assets == [("node-1",), ("node-1-child",)]
    assert import_tasks.deleted_for_nodes == [("node-1",), ("node-1-child",)]
    assert books.reevaluated == [("res-1",), ("res-1",)]
    assert nodes.deleted == []
    assert nodes.deleted_batches == [("node-1-child",), ("node-1",)]
    assert uow.events == [
        "begin",
        "commit",
        "begin",
        "commit",
        "begin",
        "commit",
        "begin",
        "commit",
        "begin",
        "commit",
        "begin",
        "commit",
        "begin",
        "commit",
    ]


def test_delete_source_node_uses_measured_bounded_default_batches() -> None:
    class LargeSourceTree(FakeSourceNodes):
        def list_subtree_ids(self, source_node_id: str) -> tuple[str, ...]:
            return (source_node_id,) + tuple(
                f"{source_node_id}-child-{index}" for index in range(1_200)
            )

    nodes = LargeSourceTree()
    books = FakeBooks()
    import_tasks = FakeImportTasks()

    result = DeleteSourceNode(
        source_nodes=nodes,
        books_resources=books,
        import_tasks=import_tasks,
        uow=RecordingUoW(),
        log=FakeLog(),
    ).execute("node-1")

    assert result.ok is True
    assert [len(batch) for batch in books.deleted_assets] == [200] * 6 + [1]
    assert [len(batch) for batch in import_tasks.deleted_for_nodes] == [500, 500, 201]
    assert [len(batch) for batch in nodes.deleted_batches[:-1]] == [500, 500, 200]
    assert nodes.deleted_batches[-1] == ("node-1",)


def test_delete_missing_source_node() -> None:
    result = DeleteSourceNode(
        source_nodes=FakeSourceNodes(),
        books_resources=FakeBooks(),
        import_tasks=FakeImportTasks(),
        uow=RecordingUoW(),
        log=FakeLog(),
    ).execute("missing")
    assert result.ok is False
    assert result.code == "SOURCE_NODE_NOT_FOUND"


def test_change_organization_mode_deletes_overlay_then_updates() -> None:
    books = FakeBooks()
    libraries = FakeLibraries()
    import_tasks = FakeImportTasks()
    uow = RecordingUoW()
    result = ChangeLibraryOrganizationMode(
        libraries=libraries,
        books_resources=books,
        import_tasks=import_tasks,
        uow=uow,
        log=FakeLog(),
    ).execute("lib-1", "VOLUMES")
    assert result.ok is True
    assert books.deleted_overlay == ["lib-1"]
    assert libraries.modes == [("lib-1", TargetLibraryOrganizationMode.VOLUMES)]
    assert import_tasks.fresh_scans == ["lib-1"]
    # Overlay wipe precedes mode update within the same transaction.
    assert uow.events == ["begin", "commit"]


def test_change_organization_mode_rejects_audiobook() -> None:
    result = ChangeLibraryOrganizationMode(
        libraries=FakeLibraries(),
        books_resources=FakeBooks(),
        import_tasks=FakeImportTasks(),
        uow=RecordingUoW(),
        log=FakeLog(),
    ).execute("lib-1", "AUDIOBOOK")
    assert result.ok is False
    assert result.code == "UNSUPPORTED_MODE"


def test_relocate_root_checks_filesystem_outside_transaction(tmp_path: Path) -> None:
    new_root = tmp_path / "new-root"
    new_root.mkdir()
    libraries = FakeLibraries()
    filesystem = FakeFilesystem(readable=True)
    uow = RecordingUoW()
    result = RelocateLibraryRoot(
        libraries=libraries, filesystem=filesystem, uow=uow, log=FakeLog()
    ).execute("lib-1", new_root)
    assert result.ok is True
    assert uow.events[0] == "release"
    assert "begin" in uow.events
    assert libraries.roots[0][0] == "lib-1"
    assert libraries.roots[0][1] == new_root.resolve()


def test_relocate_root_not_readable(tmp_path: Path) -> None:
    result = RelocateLibraryRoot(
        libraries=FakeLibraries(),
        filesystem=FakeFilesystem(readable=False),
        uow=RecordingUoW(),
        log=FakeLog(),
    ).execute("lib-1", tmp_path / "missing")
    assert result.ok is False
    assert result.code == "ROOT_NOT_READABLE"


def test_relocate_root_conflict(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    libraries = FakeLibraries()
    libraries.conflict = True
    result = RelocateLibraryRoot(
        libraries=libraries,
        filesystem=FakeFilesystem(readable=True),
        uow=RecordingUoW(),
        log=FakeLog(),
    ).execute("lib-1", root)
    assert result.ok is False
    assert result.code == "ROOT_CONFLICT"


def test_enable_and_disable_resource() -> None:
    books = FakeBooks()
    EnableReadableResource(
        books_resources=books, uow=RecordingUoW(), log=FakeLog()
    ).execute("res-1")
    DisableReadableResource(
        books_resources=books, uow=RecordingUoW(), log=FakeLog()
    ).execute("res-1")
    assert books.enablements == [
        ("res-1", ResourceEnablementState.ENABLED),
        ("res-1", ResourceEnablementState.DISABLED),
    ]


def test_enable_missing_resource() -> None:
    result = EnableReadableResource(
        books_resources=FakeBooks(), uow=RecordingUoW(), log=FakeLog()
    ).execute("missing")
    assert result.ok is False
    assert result.code == "RESOURCE_NOT_FOUND"
