from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from app.modules.imports.application.readable_resource.ports import DirectoryEntry
from app.modules.imports.application.readable_resource.scan_source_tree import (
    ScanLibrarySourceTree,
)
from app.modules.imports.domain.directory_probe import (
    DirectoryProbeDecision,
    DirectoryProbeEvidence,
    ProbeInterpretationResult,
    ProbeTerminationReason,
)
from app.modules.library.domain.organization_modes import TargetLibraryOrganizationMode
from app.modules.library.domain.source_nodes import SourceNodePhysicalKind
from app.modules.library.application.source_tree_ports import (
    InterpretationRecord,
    LibrarySourceTreeConfig,
    ObservedSourceEntry,
    SourceNodeRecord,
)


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
        self.in_transaction = False

    def rollback(self) -> None:
        self.events.append("rollback")
        self.in_transaction = False


class RecordingFilesystem:
    def __init__(self, uow: RecordingUoW, entries: dict[str, list[DirectoryEntry]]) -> None:
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
        key = absolute_directory.name if absolute_directory.name else str(absolute_directory)
        # Prefer mapping by relative key stored as path string ends.
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

    def get_by_path_key(self, library_id: str, path_key: str) -> SourceNodeRecord | None:
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

    def refresh_observed(self, source_node_id: str, entry: ObservedSourceEntry) -> SourceNodeRecord:
        raise NotImplementedError

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

    def cas_set_active_import_run(self, *args: object, **kwargs: object) -> bool:
        return True

    def set_enablement(self, *args: object, **kwargs: object) -> None:
        return None

    def publish_resource(self, **kwargs: object) -> None:
        return None

    def mark_resource_failed(self, resource_id: str) -> None:
        return None

    def clear_active_import_run(self, resource_id: str) -> None:
        return None

    def upsert_asset(self, **kwargs: object) -> str:
        return "asset-1"

    def count_ready_assets_for_published_run(
        self, resource_id: str, published_run_id: str
    ) -> int:
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

    def cleanup_stale_assets(self, resource_id: str, published_run_id: str) -> None:
        return None


class FakeImportRuns:
    def create_run(self, **kwargs: object) -> str:
        return "run-1"

    def set_run_state(self, *args: object, **kwargs: object) -> None:
        return None

    def attach_resource(self, run_id: str, resource_id: str) -> None:
        return None

    def upsert_resource_candidate(self, **kwargs: object) -> None:
        return None

    def upsert_asset_candidate(self, **kwargs: object) -> None:
        return None

    def count_ready_asset_candidates(self, import_run_id: str) -> int:
        return 0

    def list_ready_asset_candidates(self, import_run_id: str) -> tuple[object, ...]:
        return ()

    def count_incomplete_tasks(self, owner_import_run_id: str) -> int:
        return 0

    def count_failed_tasks(self, owner_import_run_id: str) -> int:
        return 0

    def create_task(self, **kwargs: object) -> object:
        raise NotImplementedError

    def get_task(self, task_id: str) -> None:
        return None

    def mark_task_state(self, *args: object, **kwargs: object) -> None:
        return None

    def cleanup_run_candidates(self, run_id: str) -> None:
        return None

    def get_run(self, run_id: str) -> None:
        return None

    def get_resource_candidate(self, run_id: str) -> None:
        return None

    def mark_discovery_complete(self, run_id: str) -> None:
        return None

    def is_discovery_complete(self, run_id: str) -> bool:
        return True


class FakeQueue:
    def __init__(self) -> None:
        self.queued = 0

    def queued_item_count(self) -> int:
        return self.queued

    def enqueue_library_import_task(self, task_id: str) -> None:
        self.queued += 1

    def enqueue_library_scan(self, library_id: str) -> None:
        return None

    def claim_next(self, worker_id: str, *, lease_seconds: int) -> None:
        return None

    def complete(self, claim: object) -> bool:
        return True

    def heartbeat(self, claim: object) -> bool:
        return True

    def is_claim_valid(self, claim: object) -> bool:
        return True

    def fence_claim(self, claim: object, *, lease_seconds: int) -> bool:
        return True

    def release_and_requeue(self, claim: object, *, delay_seconds: int = 5) -> bool:
        return True


class FakeClock:
    def now(self) -> datetime:
        return datetime(2024, 1, 1, tzinfo=timezone.utc)


class FakeLog:
    def emit(self, event: str, **kwargs: object) -> None:
        return None


def _config(root: Path, *, high_water: int = 1000) -> LibrarySourceTreeConfig:
    return LibrarySourceTreeConfig(
        library_id="lib-1",
        root_path=root,
        organization_mode=TargetLibraryOrganizationMode.FLAT,
        ignore_hidden=True,
        ignore_patterns=None,
        global_ignore_patterns="",
        min_file_size_bytes=0,
        queue_high_water=high_water,
        probe_sample_limit=100,
        probe_max_entries=10_000,
        probe_max_depth=8,
        probe_time_budget_ms=5_000,
    )


def test_scan_performs_io_only_outside_transactions(tmp_path: Path) -> None:
    root = tmp_path / "books"
    root.mkdir()
    # 40 plain files without adapters → insert nodes, short txns, no probe enqueue.
    file_entries: list[DirectoryEntry] = [
        (f"note-{i:02d}.md", SourceNodePhysicalKind.REGULAR_FILE, 1, i)
        for i in range(40)
    ]
    uow = RecordingUoW()
    filesystem = RecordingFilesystem(uow, {"books": file_entries, ".": file_entries})
    # Map root absolute path.
    filesystem._entries[str(root)] = file_entries  # noqa: SLF001
    filesystem._entries[str(root.resolve())] = file_entries  # noqa: SLF001

    scan = ScanLibrarySourceTree(
        libraries=FakeLibraries(_config(root)),
        filesystem=filesystem,
        source_nodes=FakeSourceNodes(),
        books_resources=FakeBooks(),
        import_runs=FakeImportRuns(),
        queue=FakeQueue(),
        uow=uow,
        clock=FakeClock(),
        log=FakeLog(),
    )
    result = scan.execute("lib-1")
    assert result.nodes_inserted == 40
    assert filesystem.io_while_in_txn == []
    assert "release" in uow.events
    # Many short transactions (config load + queue checks + per-file writes).
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
    filesystem._entries[str(root)] = entries  # noqa: SLF001
    filesystem._entries[str(root.resolve())] = entries  # noqa: SLF001
    filesystem._entries[str(root / "Audiobook")] = []  # noqa: SLF001

    scan = ScanLibrarySourceTree(
        libraries=FakeLibraries(_config(root)),
        filesystem=filesystem,
        source_nodes=FakeSourceNodes(),
        books_resources=FakeBooks(),
        import_runs=FakeImportRuns(),
        queue=FakeQueue(),
        uow=uow,
        clock=FakeClock(),
        log=FakeLog(),
    )
    scan.execute("lib-1")
    assert filesystem.probe_calls >= 1
    assert filesystem.io_while_in_txn == []
