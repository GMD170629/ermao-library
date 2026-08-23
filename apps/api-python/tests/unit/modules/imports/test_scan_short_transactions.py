"""Unit coverage: scan FS/probe I/O stays outside DB transactions."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.modules.imports.application.readable_resource.ports import (
    DirectoryEntry,
    LibraryImportTaskRecord,
)
from app.modules.imports.application.readable_resource.scan_source_tree import (
    ScanLibrarySourceTree,
)
from app.modules.imports.domain.directory_probe import (
    DirectoryProbeDecision,
    DirectoryProbeEvidence,
    ProbeInterpretationResult,
    ProbeTerminationReason,
)
from app.modules.library.application.source_tree_ports import (
    InterpretationRecord,
    LibrarySourceTreeConfig,
    ObservedSourceEntry,
    SourceNodeRecord,
)
from app.modules.library.domain.organization_modes import TargetLibraryOrganizationMode
from app.modules.library.domain.source_nodes import SourceNodePhysicalKind


class RecordingUoW:
    def __init__(self) -> None:
        self.in_transaction = False
        self.events: list[str] = []
        self.txn_count = 0

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self.in_transaction = True
        self.txn_count += 1
        self.events.append("begin")
        try:
            yield
            self.events.append("commit")
        finally:
            self.in_transaction = False

    def release_before_io(self) -> None:
        self.events.append("release")
        assert not self.in_transaction

    def rollback(self) -> None:
        self.events.append("rollback")
        self.in_transaction = False


class RecordingFilesystem:
    def __init__(
        self, uow: RecordingUoW, entries: dict[str, list[DirectoryEntry]]
    ) -> None:
        self._uow = uow
        self._entries = entries
        self.io_while_in_txn: list[str] = []
        self.probe_calls = 0

    def resolve_under_root(self, root: Path, relative_path: str) -> Path:
        if self._uow.in_transaction:
            self.io_while_in_txn.append(f"resolve:{relative_path}")
        return root / relative_path

    def iter_directory_entries(
        self, absolute_directory: Path
    ) -> Iterator[DirectoryEntry]:
        if self._uow.in_transaction:
            self.io_while_in_txn.append(f"scandir:{absolute_directory}")
        for stored, items in self._entries.items():
            if str(absolute_directory).endswith(stored) or stored == ".":
                yield from items
                return
        yield from ()

    def probe_directory(
        self,
        *,
        root: Path,
        directory_relative_path: str,
        ignore_hidden: bool,
        ignore_patterns: str | None,
        global_ignore_patterns: str,
        sample_limit: int,
        max_entries: int,
        max_depth: int,
        time_budget_ms: int,
    ) -> tuple[DirectoryProbeDecision, ProbeTerminationReason]:
        if self._uow.in_transaction:
            self.io_while_in_txn.append(f"probe:{directory_relative_path}")
        self.probe_calls += 1
        evidence = DirectoryProbeEvidence(
            sample_relative_paths=(),
            sample_count=0,
            entries_visited=0,
            max_depth_reached=0,
            termination_reason=ProbeTerminationReason.COMPLETE_SUBTREE,
        )
        decision = DirectoryProbeDecision(
            result=ProbeInterpretationResult.NODE_ONLY,
            adapter=None,
            reason_code="NO_SAMPLES",
            evidence=evidence,
        )
        return decision, ProbeTerminationReason.COMPLETE_SUBTREE

    def path_is_readable_directory(self, path: Path) -> bool:
        return True


class FakeLibraries:
    def __init__(self, config: LibrarySourceTreeConfig) -> None:
        self._config = config

    def get_library(self, library_id: str) -> LibrarySourceTreeConfig:
        return self._config

    def source_node_count(self, library_id: str) -> int:
        return 0

    def update_organization_mode(self, library_id: str, mode: object) -> None:
        raise NotImplementedError

    def update_root_path(self, library_id: str, root_path: Path) -> None:
        raise NotImplementedError

    def root_path_conflicts(self, root_path: Path, *, exclude_library_id: str) -> bool:
        return False


class FakeSourceNodes:
    def __init__(self) -> None:
        self._by_id: dict[str, SourceNodeRecord] = {}
        self._by_key: dict[tuple[str, str], SourceNodeRecord] = {}
        self._seq = 0
        self.inserts = 0

    def get_by_path_key(
        self, library_id: str, path_key: str
    ) -> SourceNodeRecord | None:
        return self._by_key.get((library_id, path_key))

    def get(self, source_node_id: str) -> SourceNodeRecord | None:
        return self._by_id.get(source_node_id)

    def insert_if_absent(
        self,
        *,
        library_id: str,
        parent_id: str | None,
        entry: ObservedSourceEntry,
    ) -> tuple[SourceNodeRecord, bool]:
        key = (library_id, entry.relative_path.path_key)
        existing = self._by_key.get(key)
        if existing is not None:
            return existing, False
        self._seq += 1
        node = SourceNodeRecord(
            id=f"node-{self._seq}",
            library_id=library_id,
            parent_id=parent_id,
            relative_path=entry.relative_path.value,
            path_key=entry.relative_path.path_key,
            name=entry.relative_path.name,
            physical_kind=entry.physical_kind,
            observed_size_bytes=entry.observed_size_bytes,
            observed_mtime_ns=entry.observed_mtime_ns,
            observed_at=entry.observed_at,
        )
        self._by_id[node.id] = node
        self._by_key[key] = node
        self.inserts += 1
        return node, True

    def list_subtree_ids(self, source_node_id: str) -> tuple[str, ...]:
        return (source_node_id,)

    def delete_subtree(self, source_node_id: str) -> None:
        raise NotImplementedError

    def get_interpretation(self, source_node_id: str) -> InterpretationRecord | None:
        return None

    def upsert_interpretation(self, **kwargs: object) -> None:
        return None


class FakeBooks:
    def get_book_id_for_source_node(self, source_node_id: str) -> str | None:
        return None

    def ensure_book(self, **kwargs: object) -> str:
        return "book-1"

    def get_resource_by_source_node(self, source_node_id: str) -> None:
        return None

    def get_resource(self, resource_id: str) -> None:
        return None

    def create_pending_resource(self, **kwargs: object) -> None:
        raise NotImplementedError

    def set_enablement(self, *args: object, **kwargs: object) -> None:
        return None

    def mark_resource_ready(self, **kwargs: object) -> None:
        return None

    def mark_resource_failed(self, resource_id: str) -> None:
        return None

    def upsert_asset(self, **kwargs: object) -> str:
        return "asset-1"

    def count_ready_assets(self, resource_id: str) -> int:
        return 0

    def find_outermost_directory_resource(
        self, library_id: str, relative_path: str
    ) -> None:
        return None

    def delete_library_overlay_rows(self, library_id: str) -> None:
        return None

    def delete_assets_for_source_nodes(
        self, source_node_ids: object
    ) -> tuple[str, ...]:
        return ()

    def reevaluate_ready_after_asset_loss(self, resource_ids: object) -> None:
        return None


class FakeQueue:
    def enqueue(self, **kwargs: object) -> LibraryImportTaskRecord:
        raise NotImplementedError

    def ensure_import_asset_task(self, **kwargs: object) -> None:
        return None

    def next_queued(self) -> None:
        return None

    def get_task(self, task_id: str) -> None:
        return None

    def mark_running(self, task_id: str, *, started_at: datetime) -> None:
        return None

    def mark_succeeded(self, task_id: str, *, finished_at: datetime) -> None:
        return None

    def mark_failed(
        self, task_id: str, *, error_summary: str, finished_at: datetime
    ) -> None:
        return None

    def fail_interrupted_tasks_on_startup(self, *, finished_at: datetime) -> int:
        return 0

    def requeue_failed_for_library(self, library_id: str) -> int:
        return 0

    def requeue_failed_for_source(self, source_node_id: str) -> int:
        return 0

    def has_active_kind(self, **kwargs: object) -> bool:
        return False


class FakeClock:
    def now(self) -> datetime:
        return datetime(2024, 1, 1, tzinfo=UTC)


class FakeLog:
    def __init__(self) -> None:
        self.events: list[str] = []

    def emit(self, event: str, **kwargs: object) -> None:
        self.events.append(event)


class DemandDrivenDirectoryFilesystem:
    """Yields entries only after the previous insert has completed.

    Conceptually models a huge directory (``conceptual_size`` entries) without
    creating that many objects. If the scanner materializes with ``list()``
    (or any batch larger than one), the second yield fails immediately because
    no insert has happened yet.
    """

    def __init__(
        self,
        *,
        uow: RecordingUoW,
        source_nodes: FakeSourceNodes,
        conceptual_size: int,
        process_limit: int,
        fail_after_yields: int | None = None,
    ) -> None:
        if process_limit < 2:
            raise ValueError("process_limit must be at least 2 to detect list()")
        if conceptual_size < process_limit:
            raise ValueError("conceptual_size must cover process_limit")
        self._uow = uow
        self._source_nodes = source_nodes
        self._conceptual_size = conceptual_size
        self._process_limit = process_limit
        self._fail_after_yields = fail_after_yields
        self.yielded = 0
        self.max_outstanding = 0
        self.io_while_in_txn: list[str] = []
        self.probe_calls = 0

    def resolve_under_root(self, root: Path, relative_path: str) -> Path:
        if self._uow.in_transaction:
            self.io_while_in_txn.append(f"resolve:{relative_path}")
        return root / relative_path

    def iter_directory_entries(
        self, absolute_directory: Path
    ) -> Iterator[DirectoryEntry]:
        del absolute_directory
        if self._uow.in_transaction:
            self.io_while_in_txn.append("scandir")
        for index in range(self._conceptual_size):
            outstanding = self.yielded - self._source_nodes.inserts
            self.max_outstanding = max(self.max_outstanding, outstanding)
            if index > 0 and self._source_nodes.inserts < index:
                raise AssertionError(
                    "directory entry yielded before previous entry was inserted; "
                    "scanner likely materialized the iterator with list() or a batch"
                )
            if self.yielded >= self._process_limit:
                return
            if (
                self._fail_after_yields is not None
                and self.yielded >= self._fail_after_yields
            ):
                raise OSError("simulated mid-iteration directory failure")
            self.yielded += 1
            outstanding = self.yielded - self._source_nodes.inserts
            self.max_outstanding = max(self.max_outstanding, outstanding)
            yield (
                f"note-{index:07d}.md",
                SourceNodePhysicalKind.REGULAR_FILE,
                1,
                index,
            )

    def probe_directory(
        self,
        *,
        root: Path,
        directory_relative_path: str,
        ignore_hidden: bool,
        ignore_patterns: str | None,
        global_ignore_patterns: str,
        sample_limit: int,
        max_entries: int,
        max_depth: int,
        time_budget_ms: int,
    ) -> tuple[DirectoryProbeDecision, ProbeTerminationReason]:
        del (
            root,
            directory_relative_path,
            ignore_hidden,
            ignore_patterns,
            global_ignore_patterns,
            sample_limit,
            max_entries,
            max_depth,
            time_budget_ms,
        )
        if self._uow.in_transaction:
            self.io_while_in_txn.append("probe")
        self.probe_calls += 1
        evidence = DirectoryProbeEvidence(
            sample_relative_paths=(),
            sample_count=0,
            entries_visited=0,
            max_depth_reached=0,
            termination_reason=ProbeTerminationReason.COMPLETE_SUBTREE,
        )
        decision = DirectoryProbeDecision(
            result=ProbeInterpretationResult.NODE_ONLY,
            adapter=None,
            reason_code="NO_SAMPLES",
            evidence=evidence,
        )
        return decision, ProbeTerminationReason.COMPLETE_SUBTREE

    def path_is_readable_directory(self, path: Path) -> bool:
        del path
        return True


def _config(root: Path) -> LibrarySourceTreeConfig:
    return LibrarySourceTreeConfig(
        library_id="lib-1",
        root_path=root,
        organization_mode=TargetLibraryOrganizationMode.FLAT,
        ignore_hidden=True,
        ignore_patterns=None,
        global_ignore_patterns="",
        probe_sample_limit=100,
        probe_max_entries=10_000,
        probe_max_depth=8,
        probe_time_budget_ms=5_000,
    )


def test_scan_performs_io_only_outside_transactions(tmp_path: Path) -> None:
    root = tmp_path / "books"
    root.mkdir()
    file_entries: list[DirectoryEntry] = [
        (f"note-{i:02d}.md", SourceNodePhysicalKind.REGULAR_FILE, 1, i)
        for i in range(40)
    ]
    uow = RecordingUoW()
    filesystem = RecordingFilesystem(uow, {"books": file_entries, ".": file_entries})
    filesystem._entries[str(root)] = file_entries
    filesystem._entries[str(root.resolve())] = file_entries

    scan = ScanLibrarySourceTree(
        libraries=FakeLibraries(_config(root)),
        filesystem=filesystem,
        source_nodes=FakeSourceNodes(),
        books_resources=FakeBooks(),
        queue=FakeQueue(),
        uow=uow,
        clock=FakeClock(),
        log=FakeLog(),
    )
    result = scan.execute_library("lib-1")
    assert result.nodes_inserted == 40
    assert filesystem.io_while_in_txn == []
    assert "release" in uow.events
    assert uow.txn_count >= 40
    assert uow.events.count("commit") == uow.txn_count


def test_scan_releases_before_directory_probe(tmp_path: Path) -> None:
    root = tmp_path / "books"
    root.mkdir()
    entries: list[DirectoryEntry] = [
        ("Audiobook", SourceNodePhysicalKind.DIRECTORY, None, 1),
    ]
    uow = RecordingUoW()
    filesystem = RecordingFilesystem(uow, {})
    filesystem._entries[str(root)] = entries
    filesystem._entries[str(root.resolve())] = entries
    filesystem._entries[str(root / "Audiobook")] = []

    scan = ScanLibrarySourceTree(
        libraries=FakeLibraries(_config(root)),
        filesystem=filesystem,
        source_nodes=FakeSourceNodes(),
        books_resources=FakeBooks(),
        queue=FakeQueue(),
        uow=uow,
        clock=FakeClock(),
        log=FakeLog(),
    )
    scan.execute_library("lib-1")
    assert filesystem.probe_calls >= 1
    assert filesystem.io_while_in_txn == []


def test_full_source_scan_consumes_directory_iterator_incrementally(
    tmp_path: Path,
) -> None:
    """Fail if scan materializes the directory iterator before processing."""
    root = tmp_path / "books"
    root.mkdir()
    uow = RecordingUoW()
    source_nodes = FakeSourceNodes()
    process_limit = 8
    filesystem = DemandDrivenDirectoryFilesystem(
        uow=uow,
        source_nodes=source_nodes,
        conceptual_size=1_000_000,
        process_limit=process_limit,
    )
    scan = ScanLibrarySourceTree(
        libraries=FakeLibraries(_config(root)),
        filesystem=filesystem,
        source_nodes=source_nodes,
        books_resources=FakeBooks(),
        queue=FakeQueue(),
        uow=uow,
        clock=FakeClock(),
        log=FakeLog(),
    )
    result = scan.execute_library("lib-1")
    assert result.nodes_inserted == process_limit
    assert source_nodes.inserts == process_limit
    assert filesystem.yielded == process_limit
    assert filesystem.max_outstanding <= 1
    assert filesystem.io_while_in_txn == []
    assert "release" in uow.events
    assert uow.txn_count >= process_limit


def test_full_source_scan_tolerates_oserror_mid_directory_iteration(
    tmp_path: Path,
) -> None:
    root = tmp_path / "books"
    root.mkdir()
    uow = RecordingUoW()
    source_nodes = FakeSourceNodes()
    log = FakeLog()
    filesystem = DemandDrivenDirectoryFilesystem(
        uow=uow,
        source_nodes=source_nodes,
        conceptual_size=1_000_000,
        process_limit=8,
        fail_after_yields=3,
    )
    scan = ScanLibrarySourceTree(
        libraries=FakeLibraries(_config(root)),
        filesystem=filesystem,
        source_nodes=source_nodes,
        books_resources=FakeBooks(),
        queue=FakeQueue(),
        uow=uow,
        clock=FakeClock(),
        log=log,
    )
    result = scan.execute_library("lib-1")
    assert result.nodes_inserted == 3
    assert source_nodes.inserts == 3
    assert "source_tree.scan.directory_unreadable" in log.events
    assert "source_tree.scan.completed" in log.events
    assert filesystem.io_while_in_txn == []


class _InsertRaisesOSErrorSourceNodes(FakeSourceNodes):
    """Raises OSError during first SourceNode write (entry processing, not scandir)."""

    def insert_if_absent(
        self,
        *,
        library_id: str,
        parent_id: str | None,
        entry: ObservedSourceEntry,
    ) -> tuple[SourceNodeRecord, bool]:
        raise OSError("simulated source-node repository write failure")


def test_entry_processing_oserror_is_not_swallowed_as_unreadable_directory(
    tmp_path: Path,
) -> None:
    root = tmp_path / "books"
    root.mkdir()
    file_entries: list[DirectoryEntry] = [
        ("note-00.md", SourceNodePhysicalKind.REGULAR_FILE, 1, 0),
        ("note-01.md", SourceNodePhysicalKind.REGULAR_FILE, 1, 1),
    ]
    uow = RecordingUoW()
    log = FakeLog()
    filesystem = RecordingFilesystem(uow, {})
    filesystem._entries[str(root)] = file_entries
    filesystem._entries[str(root.resolve())] = file_entries

    scan = ScanLibrarySourceTree(
        libraries=FakeLibraries(_config(root)),
        filesystem=filesystem,
        source_nodes=_InsertRaisesOSErrorSourceNodes(),
        books_resources=FakeBooks(),
        queue=FakeQueue(),
        uow=uow,
        clock=FakeClock(),
        log=log,
    )
    with pytest.raises(OSError, match="simulated source-node repository write failure"):
        scan.execute_library("lib-1")
    assert "source_tree.scan.directory_unreadable" not in log.events
    assert filesystem.io_while_in_txn == []
