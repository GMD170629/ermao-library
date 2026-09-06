"""Protect load evidence against lost acknowledgements and undercounted resources."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import time
from collections import Counter
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
import psutil
import pytest
import python_release_load_precheck as precheck
from app.db.base import Base
from app.models import (
    Library,
    LibraryBook,
    LibraryReadableResource,
    LibraryResourceAsset,
    LibrarySourceNode,
)
from app.modules.library.public import SourceNodeRelativePath
from python_release_load_precheck import (
    CorpusConfig,
    FileRecord,
    LoadDriver,
    PhaseState,
    ResourceSampler,
    _freeze_scan_settings,
    _machine_snapshot,
    _request_summaries,
    _seed_rescan_sentinels,
    _supervise_measurement_process,
    _verify_scan_integrity,
    _verify_source_hashes,
    _write_failure_evidence,
    stage_dataset,
)
from python_smoke_process import start_logged_process
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session


def make_source(root: Path, index: int) -> FileRecord:
    relative = f"group-{index}/sample-{index}.epub"
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    content = f"original-{index}".encode()
    path.write_bytes(content)
    return FileRecord(
        relative,
        "epub",
        f"sample-{index}",
        index,
        "small",
        len(content),
        hashlib.sha256(content).hexdigest(),
    )


def add_sample_identity(
    db: Session, record: FileRecord, library_id: str = "owned"
) -> None:
    suffix = f"{library_id}-{record.ordinal}"
    for node_id, relative, kind in (
        (
            f"book-node-{suffix}",
            str(Path(record.relative_path).parent).replace("\\", "/"),
            "DIRECTORY",
        ),
        (f"file-node-{suffix}", record.relative_path, "REGULAR_FILE"),
    ):
        db.add(
            LibrarySourceNode(
                id=node_id,
                library_id=library_id,
                relative_path=relative,
                path_key=SourceNodeRelativePath(relative).path_key,
                name=Path(relative).name,
                physical_kind=kind,
                observed_size_bytes=record.size_bytes
                if kind == "REGULAR_FILE"
                else None,
                observed_mtime_ns=1,
                observed_at=datetime(2026, 9, 6, tzinfo=UTC),
            )
        )
    db.flush()
    db.add(
        LibraryBook(
            id=f"book-{suffix}",
            library_id=library_id,
            source_node_id=f"book-node-{suffix}",
        )
    )
    db.flush()
    db.add(
        LibraryReadableResource(
            id=f"resource-{suffix}",
            library_id=library_id,
            book_id=f"book-{suffix}",
            source_node_id=f"file-node-{suffix}",
            adapter_id="epub",
            adapter_version="1",
            format=record.format,
            import_state="READY",
        )
    )
    db.flush()
    db.add(
        LibraryResourceAsset(
            id=f"asset-{suffix}",
            library_id=library_id,
            resource_id=f"resource-{suffix}",
            source_node_id=f"file-node-{suffix}",
            role="PRIMARY",
            import_state="READY",
        )
    )


@pytest.fixture
def integrity_library(tmp_path: Path):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(
        engine,
        tables=[
            model.__table__
            for model in (
                Library,
                LibrarySourceNode,
                LibraryBook,
                LibraryReadableResource,
                LibraryResourceAsset,
            )
        ],
    )
    source_root = tmp_path / "source"
    records = [make_source(source_root, index) for index in range(2)]
    with Session(engine) as db, db.begin():
        for library_id in ("owned", "unrelated"):
            db.add(
                Library(
                    id=library_id,
                    name=library_id,
                    root_path=library_id,
                    organization_mode="FLAT",
                )
            )
        db.flush()
        for record in records:
            add_sample_identity(db, record)
        add_sample_identity(db, records[0], "unrelated")
    try:
        yield engine, source_root, records
    finally:
        engine.dispose()


@pytest.mark.parametrize("damage", ["same_size", "size", "missing"])
def test_source_hashes_reopen_originals_and_preserve_failure_report(
    tmp_path: Path,
    damage: str,
) -> None:
    source = tmp_path / "source"
    record = make_source(source, 0)
    _verify_source_hashes(source, [record], tmp_path / "before.json")
    path = source / record.relative_path
    if damage == "missing":
        path.unlink()
    else:
        path.write_bytes(b"x" * (record.size_bytes if damage == "same_size" else 1))
    report = tmp_path / "after.json"
    with pytest.raises(RuntimeError, match="source hash integrity failed"):
        _verify_source_hashes(source, [record], report)
    evidence = json.loads(report.read_text())
    assert evidence["status"] == "failed"
    assert evidence["verifiedFiles"] == 0
    assert evidence["failures"][0]["relativePath"] == record.relative_path
    if damage == "same_size":
        assert evidence["failures"][0]["actualSizeBytes"] == record.size_bytes
        assert evidence["failures"][0]["actualSha256"] != record.sha256


@pytest.mark.parametrize("escape", ["relative", "absolute", "symlink"])
def test_hash_check_never_reads_outside_owned_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    escape: str,
) -> None:
    source = tmp_path / "owned"
    source.mkdir()
    private = tmp_path / "private.epub"
    private.write_bytes(b"private")
    relative = "../private.epub" if escape == "relative" else str(private)
    if escape == "symlink":
        relative = "link.epub"
        original_resolve = Path.resolve

        def resolve(path: Path, *args, **kwargs) -> Path:
            return (
                private
                if path == source / relative
                else original_resolve(path, *args, **kwargs)
            )

        monkeypatch.setattr(Path, "resolve", resolve)

    def forbidden_hash(path: Path) -> str:
        pytest.fail("escaped source must not be opened")

    monkeypatch.setattr(precheck, "sha256_file", forbidden_hash)
    report = tmp_path / "integrity/source-initial-before.json"
    with pytest.raises(RuntimeError, match="source hash integrity failed"):
        _verify_source_hashes(
            source,
            [FileRecord(relative, "epub", "test", 1, "small", 7, "hash")],
            report,
        )
    assert json.loads(report.read_text())["failures"][0]["errorType"] == "ValueError"
    assert private.read_bytes() == b"private"


def test_integrity_checks_are_read_only_and_library_scoped(
    tmp_path: Path,
    integrity_library,
) -> None:
    engine, source, records = integrity_library
    originals = {
        r.relative_path: (source / r.relative_path).read_bytes() for r in records
    }
    writes: list[str] = []

    def observe(connection, clause, multiparams, params, execution_options) -> None:
        if not clause.is_select:
            writes.append(type(clause).__name__)

    event.listen(engine, "before_execute", observe)
    try:
        _verify_source_hashes(
            source, records, tmp_path / "integrity/source-rescan-after.json"
        )
        before = _verify_scan_integrity(
            engine, "owned", records, tmp_path / "before.json"
        )
        after = _verify_scan_integrity(
            engine, "owned", records, tmp_path / "after.json", previous=before
        )
    finally:
        event.remove(engine, "before_execute", observe)
    assert writes == []
    assert after.associations == before.associations
    assert len(after.associations) == len(records)
    assert {
        r.relative_path: (source / r.relative_path).read_bytes() for r in records
    } == originals
    assert json.loads((tmp_path / "after.json").read_text())["status"] == "verified"


@pytest.mark.parametrize(
    "damage",
    [
        "asset_path",
        "asset_resource_swap",
        "asset_id_swap",
        "book_swap",
        "book_replaced",
        "invalid_book_path",
        "resource_deleted",
        "resource_replaced",
        "missing_book",
        "cross_library_book",
        "orphan_asset",
        "resource_not_ready",
        "asset_not_ready",
    ],
)
def test_association_check_rejects_loss_rebinding_and_non_ready_rows(
    tmp_path: Path,
    integrity_library,
    damage: str,
) -> None:
    engine, _, records = integrity_library
    before = _verify_scan_integrity(engine, "owned", records, tmp_path / "before.json")
    with Session(engine) as db, db.begin():
        resource = db.scalars(
            select(LibraryReadableResource).where(
                LibraryReadableResource.id == "resource-owned-0"
            )
        ).one()
        asset = db.scalars(
            select(LibraryResourceAsset).where(
                LibraryResourceAsset.id == "asset-owned-0"
            )
        ).one()
        if damage == "asset_path":
            asset.source_node_id = "file-node-owned-1"
        elif damage == "asset_resource_swap":
            other = db.scalars(
                select(LibraryResourceAsset).where(
                    LibraryResourceAsset.id == "asset-owned-1"
                )
            ).one()
            asset.resource_id, other.resource_id = other.resource_id, asset.resource_id
        elif damage == "asset_id_swap":
            other = db.scalars(
                select(LibraryResourceAsset).where(
                    LibraryResourceAsset.id == "asset-owned-1"
                )
            ).one()
            asset.id = "temporary-id"
            db.flush()
            other.id = "asset-owned-0"
            db.flush()
            asset.id = "asset-owned-1"
        elif damage == "book_swap":
            resource.book_id = "book-owned-1"
        elif damage == "book_replaced":
            book = db.scalars(
                select(LibraryBook).where(LibraryBook.id == resource.book_id)
            ).one()
            book.id = resource.book_id = "replacement-book"
        elif damage == "invalid_book_path":
            node = db.scalars(
                select(LibrarySourceNode).where(
                    LibrarySourceNode.id == "book-node-owned-0"
                )
            ).one()
            node.relative_path = "../outside"
        elif damage == "resource_deleted":
            db.delete(resource)
        elif damage == "resource_replaced":
            resource.id = asset.resource_id = "replacement-resource"
        elif damage == "missing_book":
            resource.book_id = "missing"
        elif damage == "cross_library_book":
            resource.book_id = "book-unrelated-0"
        elif damage == "orphan_asset":
            db.add(
                LibraryResourceAsset(
                    id="orphan",
                    library_id="owned",
                    resource_id="missing",
                    source_node_id="file-node-owned-0",
                    role="PRIMARY",
                    import_state="READY",
                )
            )
        elif damage == "resource_not_ready":
            resource.import_state = "PENDING"
        else:
            asset.import_state = "FAILED"
    report = tmp_path / "integrity/associations-rescan-after.json"
    with pytest.raises(RuntimeError, match="resource association integrity failed"):
        _verify_scan_integrity(engine, "owned", records, report, previous=before)
    evidence = json.loads(report.read_text())
    assert evidence["status"] == "failed"
    assert not all(evidence["checks"].values())
    if damage == "asset_id_swap":
        assert evidence["identity"]["assetIdDigest"] == before.identity["assetIdDigest"]
        assert evidence["checks"]["bindingsValid"] is True
        assert evidence["checks"]["previousBindingsPreserved"] is False
    failure = _write_failure_evidence(tmp_path, "RuntimeError")
    assert failure["integrityChecks"]["associations-rescan-after"]["status"] == "failed"
    assert report.is_file()


def test_growth_preserves_existing_identities_while_adding_samples(
    tmp_path: Path,
    integrity_library,
) -> None:
    engine, source, records = integrity_library
    before = _verify_scan_integrity(engine, "owned", records, tmp_path / "before.json")
    added = make_source(source, 2)
    with Session(engine) as db, db.begin():
        add_sample_identity(db, added)
    after = _verify_scan_integrity(
        engine, "owned", records + [added], tmp_path / "growth.json", previous=before
    )
    assert set(before.associations) < set(after.associations)


@pytest.mark.parametrize("total_files", [10_000, 100_000, 300_000])
def test_measurement_integrity_failure_reaches_cli_and_keeps_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    total_files: int,
) -> None:
    run_root = tmp_path / "measurement"
    run_root.mkdir()
    (run_root / "logs").mkdir()
    state_path = tmp_path / "supervisor-state.json"
    monkeypatch.setattr(precheck, "_new_run_root", lambda label: run_root)
    monkeypatch.setattr(precheck, "_git_commit", lambda: "baseline")
    monkeypatch.setattr(precheck, "_backend_source_digest", lambda: "digest")
    monkeypatch.setattr(precheck, "_machine_snapshot", lambda root: {})

    def corrupted_dataset(
        root: Path, limit: int, *, corpus: CorpusConfig, log_path: Path
    ) -> list[FileRecord]:
        assert corpus.total_files == total_files
        assert limit == corpus.initial_files
        record = make_source(root, 0)
        (root / record.relative_path).write_bytes(b"x" * record.size_bytes)
        return [record]

    def forbidden_services(*args, **kwargs):
        pytest.fail("this test must not start services")

    monkeypatch.setattr(precheck, "generate_dataset", corrupted_dataset)
    monkeypatch.setattr(precheck, "_start_service_processes", forbidden_services)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "precheck",
            "--measure-window",
            "--measurement-child",
            "--total-files",
            str(total_files),
            "--overall-timeout-seconds",
            "20000",
            "--supervisor-state",
            str(state_path),
        ],
    )
    with pytest.raises(RuntimeError, match="source hash integrity failed"):
        precheck.main()
    assert json.loads(state_path.read_text()) == {"status": "failed"}
    failure = json.loads((run_root / "failure-summary.json").read_text())
    assert failure["integrityChecks"]["source-initial-before"]["status"] == "failed"
    assert not (run_root / "complete.json").exists()
    config = failure["runConfig"]
    assert config["totalFiles"] == total_files
    assert config["initialFiles"] == total_files // 5
    assert config["initialPercent"] == 20
    assert (
        config["initialFormatCounts"] == CorpusConfig(total_files).initial_format_counts
    )
    assert config["overallTimeoutSeconds"] == 20000
    assert config["overallTimeoutOwner"] == "supervisor"
    assert failure["releaseGateStatus"] == "not_verified"
    assert failure["limitations"] == list(precheck.PRECHECK_LIMITATIONS)


def test_latency_summary_keeps_failures_and_scan_states(tmp_path: Path) -> None:
    path = tmp_path / "requests.jsonl"
    records = [
        {
            "phase": "rescan",
            "endpoint": "list",
            "scanActive": active,
            "success": success,
            "elapsedMs": duration,
            "errorCode": error,
        }
        for active, success, duration, error in (
            (True, True, 100, None),
            (True, False, 10000, "timeout"),
            (False, True, 20, None),
            (True, False, None, "driver_failure"),
        )
    ]
    path.write_text("\n".join(json.dumps(record) for record in records))
    active, idle = _request_summaries(path)
    assert active["sampleCount"] == 3
    assert active["failureCount"] == 2
    assert active["latencyMs"]["p95"] == 10000
    assert active["errors"] == {"timeout": 1, "driver_failure": 1}
    assert idle["sampleCount"] == 1
    assert idle["latencyMs"]["p95"] == 20


def test_incomplete_evidence_keeps_timeout_and_missing_rescan(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "requests.jsonl").write_text(
        json.dumps(
            {
                "phase": "idle",
                "endpoint": "search",
                "scanActive": False,
                "success": False,
                "errorType": "ReadTimeout",
                "elapsedMs": 10000,
                "startedMonotonic": 10,
                "endedMonotonic": 20,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    result = _write_failure_evidence(tmp_path, "ReadTimeout")
    assert result["status"] == "failed"
    assert result["rescan"] == {"status": "not_verified"}
    assert result["requestSummaries"][0]["successRate"] == 0
    assert result["requestSummaries"][0]["latencyMs"]["p95"] == 10000
    assert result["requestSummaries"][0]["sampleEvidenceSufficient"] is False
    assert result["phases"] == []
    assert (tmp_path / "failure-summary.json").is_file()


def test_corpus_cannot_write_outside_test_root(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    sentinel = tmp_path / "private.txt"
    sentinel.write_text("preserve")
    record = FileRecord("../private.txt", "epub", "test", 1, "small", 8, "hash")
    with pytest.raises(ValueError, match="escapes"):
        stage_dataset(
            source,
            target,
            [record],
            start_index=0,
            end_index=1,
            log_path=tmp_path / "stage.log",
        )
    assert sentinel.read_text() == "preserve"
    assert list(target.iterdir()) == []


def test_resource_sampler_counts_real_child_memory(tmp_path: Path) -> None:
    ready = tmp_path / "ready"
    child_code = (
        "import time; from pathlib import Path; "
        "memory=bytearray(32*1024*1024); "
        f"Path({str(ready)!r}).write_text('ready'); time.sleep(30)"
    )
    parent_code = (
        "import subprocess, sys; "
        f"child=subprocess.Popen([sys.executable, '-c', {child_code!r}]); child.wait()"
    )
    process = start_logged_process(
        [sys.executable, "-c", parent_code],
        cwd=tmp_path,
        env=os.environ,
        log_path=tmp_path / "tree.log",
    )
    try:
        deadline = time.monotonic() + 15
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert ready.exists(), "child allocation did not become ready"
        root_rss = psutil.Process(process.process.pid).memory_info().rss
        total, pids = ResourceSampler._rss(process.process.pid)
        assert process.process.pid in pids
        assert len(pids) >= 2
        assert total >= root_rss + 32 * 1024 * 1024
    finally:
        process.stop(timeout=2)


class ProgressServer:
    def __init__(self) -> None:
        self.snapshots: dict[str, dict[str, object]] = {}
        self.corrupt_ack = False

    def handle(self, request: httpx.Request) -> httpx.Response:
        resource = request.url.path.split("/")[-2]
        if request.method == "PUT":
            payload = json.loads(request.content)
            snapshot = {**payload, "revision": 1, "receivedAtEpochMillis": 1}
            self.snapshots[resource] = snapshot
            if self.corrupt_ack:
                snapshot["position"]["locator"] = {"wrong": True}
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "data": {
                        "acceptedMutationId": payload["mutationId"],
                        "acceptedRevision": 1,
                        "currentSnapshot": snapshot,
                    },
                },
            )
        return httpx.Response(
            200,
            json={
                "ok": True,
                "data": {
                    "schemaVersion": 5,
                    "progressSnapshot": self.snapshots.get(resource),
                },
            },
        )


def make_driver(tmp_path: Path) -> LoadDriver:
    return LoadDriver(
        base_url="http://test",
        cookies={},
        pool={"bookIds": ["book"], "resourceIds": ["resource"], "formats": ["epub"]},
        phase="test",
        state=PhaseState(),
        output_path=tmp_path / "requests.jsonl",
        abort_event=threading.Event(),
        duration_seconds=1,
        requests_per_second=1,
    )


@pytest.mark.parametrize("damage", ["mutation", "position", "missing", "malformed"])
def test_progress_verification_rejects_lost_acknowledged_write(
    tmp_path: Path, damage: str
) -> None:
    server = ProgressServer()
    driver = make_driver(tmp_path)
    with httpx.Client(
        base_url="http://test", transport=httpx.MockTransport(server.handle)
    ) as client:
        assert driver._request(client, "v5_save", 0)["success"] is True
        assert driver.verify_acknowledged(client)["resourcesVerified"] == 1
        snapshot = server.snapshots["resource"]
        if damage == "mutation":
            snapshot["mutationId"] = str(uuid4())
        elif damage == "position":
            snapshot["position"]["locator"] = {"wrong": True}
        elif damage == "missing":
            del server.snapshots["resource"]
        else:
            del snapshot["revision"]
        with pytest.raises((RuntimeError, ValueError)):
            driver.verify_acknowledged(client)


def test_progress_rejects_200_ok_with_wrong_acknowledged_position(
    tmp_path: Path,
) -> None:
    server = ProgressServer()
    server.corrupt_ack = True
    driver = make_driver(tmp_path)
    with httpx.Client(
        base_url="http://test", transport=httpx.MockTransport(server.handle)
    ) as client:
        result = driver._request(client, "v5_save", 0)
    assert result["success"] is False
    assert driver.acknowledged == {}


def test_sentinels_are_excluded_from_rescan_writes(tmp_path: Path) -> None:
    server = ProgressServer()
    pool = {
        "bookIds": ["b1", "b2", "b3", "b4"],
        "resourceIds": ["r1", "r2", "r3", "r4"],
        "formats": ["epub", "pdf", "cbz", "epub"],
    }
    with httpx.Client(
        base_url="http://test", transport=httpx.MockTransport(server.handle)
    ) as client:
        sentinels, remaining = _seed_rescan_sentinels(
            client, pool, PhaseState(), tmp_path / "sentinels.json", threading.Event()
        )
    assert set(sentinels) == {"r1", "r2", "r3"}
    assert remaining["resourceIds"] == ["r4"]


def test_response_finishing_after_scan_still_counts_as_active(tmp_path: Path) -> None:
    driver = make_driver(tmp_path)
    driver.state.set("scan", scan_active=True)

    def respond(request: httpx.Request) -> httpx.Response:
        driver.state.set("scan", scan_active=False)
        return httpx.Response(200, json={"ok": True, "data": {}})

    with httpx.Client(
        base_url="http://test", transport=httpx.MockTransport(respond)
    ) as client:
        assert driver._request(client, "list", 0)["scanActive"] is True
        assert driver._request(client, "list", 1)["scanActive"] is False


@pytest.mark.parametrize("persisted", [True, False])
def test_freeze_requires_settings_readback(persisted: bool) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.method == "PUT":
            assert json.loads(request.content) == {
                "watchEnabled": False,
                "intervalMinutes": 1440,
            }
        return httpx.Response(
            200,
            json={
                "ok": True,
                "data": {"watchEnabled": not persisted, "intervalMinutes": 1440},
            },
        )

    with httpx.Client(
        base_url="http://test", transport=httpx.MockTransport(respond)
    ) as client:
        if persisted:
            assert _freeze_scan_settings(client)["watchEnabled"] is False
        else:
            with pytest.raises(RuntimeError, match="not persisted"):
                _freeze_scan_settings(client)


def test_machine_snapshot_decodes_windows_utf8(tmp_path: Path) -> None:
    if os.name != "nt":
        return  # This probe is explicitly a Windows PowerShell boundary.
    snapshot = _machine_snapshot(tmp_path)
    assert "windowsError" not in snapshot
    assert isinstance(snapshot["windows"]["osCaption"], str)


def test_supervisor_bounds_non_daemon_threads_and_descendants(tmp_path: Path) -> None:
    ready = tmp_path / "ready"
    code = (
        "import subprocess,sys,threading,time; from pathlib import Path; "
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']); "
        "threading.Thread(target=lambda: time.sleep(60)).start(); "
        f"Path({str(ready)!r}).write_text(str(child.pid)); time.sleep(60)"
    )
    process = start_logged_process(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=os.environ,
        log_path=tmp_path / "supervisor.log",
    )
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert ready.exists()
        child = psutil.Process(int(ready.read_text()))
        started = time.monotonic()
        with pytest.raises(TimeoutError, match="measurement exceeded"):
            _supervise_measurement_process(process, tmp_path / "state.json", 0.3)
        assert time.monotonic() - started < 20
        assert process.poll() is not None
        assert not child.is_running()
    finally:
        process.stop(timeout=2)


@pytest.mark.parametrize(
    ("total", "initial", "counts", "initial_counts"),
    [
        (
            10_000,
            2_000,
            {"epub": 4000, "pdf": 3000, "cbz": 3000},
            {"epub": 800, "pdf": 600, "cbz": 600},
        ),
        (
            100_000,
            20_000,
            {"epub": 40000, "pdf": 30000, "cbz": 30000},
            {"epub": 8000, "pdf": 6000, "cbz": 6000},
        ),
        (
            300_000,
            60_000,
            {"epub": 120000, "pdf": 90000, "cbz": 90000},
            {"epub": 24000, "pdf": 18000, "cbz": 18000},
        ),
    ],
)
def test_corpus_specs_cover_each_scale_without_writing_files(
    total: int, initial: int, counts: dict[str, int], initial_counts: dict[str, int]
) -> None:
    corpus = CorpusConfig(total)
    assert corpus.initial_files == initial
    assert corpus.format_counts == counts
    assert corpus.initial_format_counts == initial_counts
    observed: Counter[str] = Counter()
    initial_observed: Counter[str] = Counter()
    paths: set[str] = set()
    for index, (format_name, ordinal, _, relative, _) in enumerate(
        precheck._file_specs(corpus)
    ):
        assert relative not in paths
        paths.add(relative)
        observed[format_name] += 1
        if index < initial:
            initial_observed[format_name] += 1
        assert 1 <= ordinal <= counts[format_name]
    assert len(paths) == total
    assert observed == counts
    assert initial_observed == initial_counts
    if total == 300_000:
        assert "reflowable/shard-999/precheck-epub-100000.epub" in paths
        assert "reflowable/shard-1199/precheck-epub-120000.epub" in paths


@pytest.mark.parametrize("total", [10_000, 100_000, 300_000])
def test_smoke_reopens_one_real_file_per_format_at_every_scale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, total: int
) -> None:
    monkeypatch.setattr(precheck, "_new_run_root", lambda label: tmp_path)
    monkeypatch.setattr(precheck, "_git_commit", lambda: "test")
    precheck.run_small_smoke(CorpusConfig(total))
    evidence = json.loads((tmp_path / "small-smoke.json").read_text(encoding="utf-8"))
    assert {record["format"] for record in evidence["files"]} == {"epub", "pdf", "cbz"}
    assert [record["ordinal"] for record in evidence["files"]] == [1, 1, 1]
    assert evidence["summary"]["files"] == 3
    assert evidence["corpusConfig"]["totalFiles"] == total
    assert evidence["corpusConfig"]["initialPercent"] == 20


@pytest.mark.parametrize("total", [10_000, 100_000, 300_000])
def test_generation_reopens_only_the_requested_growth_boundary_slice(
    tmp_path: Path, total: int
) -> None:
    corpus = CorpusConfig(total)
    records = precheck.generate_dataset(
        tmp_path / "library",
        corpus.initial_files + 1,
        corpus=corpus,
        start_index=corpus.initial_files - 1,
        log_path=tmp_path / "generation.log",
    )
    assert [(record.format, record.ordinal) for record in records] == [
        ("cbz", corpus.initial_format_counts["cbz"]),
        ("epub", corpus.initial_format_counts["epub"] + 1),
    ]
    assert len(list((tmp_path / "library").rglob("*.*"))) == 2
    for record in records:
        precheck._validate_file(record, tmp_path / "library")


@pytest.mark.parametrize(("start", "end"), [(-1, 1), (2, 1), (0, 10001)])
def test_generation_rejects_invalid_slice_before_writing(
    tmp_path: Path, start: int, end: int
) -> None:
    with pytest.raises(ValueError, match="outside the configured corpus"):
        precheck.generate_dataset(
            tmp_path / "library",
            end,
            corpus=CorpusConfig(),
            start_index=start,
            log_path=tmp_path / "generation.log",
        )
    assert list(tmp_path.iterdir()) == []


@pytest.fixture
def prepared_manifest(tmp_path: Path) -> Path:
    """Manifest-only fixture: never generate a large corpus or run import services."""
    corpus = CorpusConfig()
    source = tmp_path / "library"
    source.mkdir()
    records = [
        FileRecord(
            relative,
            format_name,
            f"sample-{ordinal}",
            ordinal,
            size_class,
            1,
            f"{index:064x}",
        )
        for index, (format_name, ordinal, size_class, relative, _) in enumerate(
            precheck._file_specs(corpus)
        )
    ]
    path = tmp_path / "dataset-manifest.json"
    precheck.write_json(
        path,
        {
            "status": "corpus-ready",
            "root": str(source),
            **corpus.evidence(),
            "records": [asdict(record) for record in records],
            "summary": precheck.dataset_summary(records),
            "validation": {
                "allFilesWrittenAndReopened": True,
                "databaseRowsWritten": False,
            },
        },
    )
    return path


@pytest.mark.parametrize("legacy", [False, True])
def test_prepared_manifest_keeps_existing_10k_compatibility(
    prepared_manifest: Path, legacy: bool
) -> None:
    if legacy:
        payload = json.loads(prepared_manifest.read_text(encoding="utf-8"))
        for key in CorpusConfig().evidence():
            payload.pop(key)
        precheck.write_json(prepared_manifest, payload)
    source, records = precheck._load_prepared_corpus(
        prepared_manifest.parent, CorpusConfig()
    )
    assert source == prepared_manifest.parent / "library"
    assert len(records) == 10_000
    assert Counter(record.format for record in records[:2000]) == {
        "epub": 800,
        "pdf": 600,
        "cbz": 600,
    }


@pytest.mark.parametrize(
    "damage",
    [
        "count",
        "distribution",
        "initial_distribution",
        "duplicate",
        "path",
        "summary",
        "configuration",
    ],
)
def test_prepared_manifest_rejects_self_consistent_but_wrong_corpus(
    prepared_manifest: Path, damage: str
) -> None:
    payload = json.loads(prepared_manifest.read_text(encoding="utf-8"))
    records = [FileRecord(**record) for record in payload["records"]]
    if damage == "count":
        records.pop()
    elif damage == "distribution":
        records[-1] = replace(records[-1], format="pdf")
    elif damage == "initial_distribution":
        records[800], records[2000] = records[2000], records[800]
    elif damage == "duplicate":
        records[1] = replace(records[1], relative_path=records[0].relative_path)
    elif damage == "path":
        records[0] = replace(records[0], relative_path="../private.epub")
    elif damage == "configuration":
        payload["initialPercent"] = 50
    payload["records"] = [asdict(record) for record in records]
    payload["summary"] = precheck.dataset_summary(records)
    if damage == "summary":
        payload["summary"]["bytes"] += 1
    precheck.write_json(prepared_manifest, payload)
    with pytest.raises((RuntimeError, ValueError)):
        precheck._load_prepared_corpus(prepared_manifest.parent, CorpusConfig())


def test_wrong_prepared_scale_fails_before_measurement_directory_or_services(
    prepared_manifest: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args, **kwargs):
        pytest.fail("invalid manifest must fail before creating a run or services")

    monkeypatch.setattr(precheck, "_new_run_root", forbidden)
    monkeypatch.setattr(precheck, "_start_service_processes", forbidden)
    monkeypatch.setattr(precheck, "_git_commit", lambda: "test")
    monkeypatch.setattr(precheck, "_backend_source_digest", lambda: "test")
    state = prepared_manifest.parent / "state.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "precheck",
            "--measure-window",
            "--measurement-child",
            "--supervisor-state",
            str(state),
            "--prepared-corpus-root",
            str(prepared_manifest.parent),
            "--total-files",
            "100000",
        ],
    )
    with pytest.raises(RuntimeError, match="must contain 100000"):
        precheck.main()
    assert json.loads(state.read_text()) == {"status": "failed"}


@pytest.mark.parametrize("damage", ["extra_book", "merged_books"])
def test_single_file_integrity_requires_exact_book_count(
    tmp_path: Path, integrity_library, damage: str
) -> None:
    engine, _, records = integrity_library
    with Session(engine) as db, db.begin():
        if damage == "extra_book":
            db.add(
                LibraryBook(
                    id="extra-book",
                    library_id="owned",
                    source_node_id="file-node-owned-0",
                )
            )
        else:
            records = [
                records[0],
                replace(records[1], relative_path="group-0/sample-1.epub"),
            ]
            node = db.scalars(
                select(LibrarySourceNode).where(
                    LibrarySourceNode.id == "file-node-owned-1"
                )
            ).one()
            node.relative_path = records[1].relative_path
            node.path_key = SourceNodeRelativePath(node.relative_path).path_key
            resource = db.scalars(
                select(LibraryReadableResource).where(
                    LibraryReadableResource.id == "resource-owned-1"
                )
            ).one()
            resource.book_id = "book-owned-0"
            db.delete(
                db.scalars(
                    select(LibraryBook).where(LibraryBook.id == "book-owned-1")
                ).one()
            )
    report = tmp_path / "book-count.json"
    with pytest.raises(RuntimeError, match="association integrity failed"):
        _verify_scan_integrity(engine, "owned", records, report)
    evidence = json.loads(report.read_text(encoding="utf-8"))
    assert evidence["checks"]["bindingsValid"] is True
    assert evidence["checks"]["resourceIdsUnique"] is True
    assert evidence["checks"]["countsMatchExpected"] is False


@pytest.mark.parametrize(
    "mode", ["--small-smoke", "--prepare-only", "--measure-window"]
)
@pytest.mark.parametrize("total", [10_000, 100_000, 300_000])
def test_cli_routes_selected_scale_without_executing_work(
    monkeypatch: pytest.MonkeyPatch, mode: str, total: int
) -> None:
    received: list[int] = []
    monkeypatch.setattr(
        precheck, "run_small_smoke", lambda corpus: received.append(corpus.total_files)
    )
    monkeypatch.setattr(
        precheck, "run_prepare_only", lambda corpus: received.append(corpus.total_files)
    )
    monkeypatch.setattr(
        precheck,
        "run_supervised_measurement",
        lambda args: received.append(args.total_files),
    )
    monkeypatch.setattr(sys, "argv", ["precheck", mode, "--total-files", str(total)])
    assert precheck.main() == 0
    assert received == [total]


@pytest.mark.parametrize("value", ["0", "2000", "10001", "300001", "100000.0"])
def test_cli_rejects_unsupported_scale_before_writing(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setattr(
        precheck,
        "_new_run_root",
        lambda label: pytest.fail("invalid scale must not write"),
    )
    monkeypatch.setattr(sys, "argv", ["precheck", "--total-files", value])
    with pytest.raises(SystemExit) as error:
        precheck.main()
    assert error.value.code == 2


def test_supervisor_forwards_scale_windows_and_overall_timeout_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}
    process = object()

    def start(command, **kwargs):
        captured["command"] = command
        return process

    def supervise(child, state, timeout):
        assert child is process
        captured["timeout"] = timeout
        precheck.write_json(state, {"status": "completed"})

    monkeypatch.setattr(precheck, "_new_run_root", lambda label: tmp_path)
    monkeypatch.setattr(precheck, "start_logged_process", start)
    monkeypatch.setattr(precheck, "_supervise_measurement_process", supervise)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "precheck",
            "--measure-window",
            "--total-files",
            "300000",
            "--overall-timeout-seconds",
            "20000",
            "--prepared-corpus-root",
            str(tmp_path / "corpus"),
        ],
    )
    assert precheck.main() == 0
    command = captured["command"]
    expected = {
        "--total-files": "300000",
        "--idle-window-seconds": "135",
        "--active-window-seconds": "180",
        "--request-rate": "10",
        "--scan-timeout-seconds": "2700",
        "--overall-timeout-seconds": "20000.0",
        "--prepared-corpus-root": str((tmp_path / "corpus").resolve()),
    }
    for flag, value in expected.items():
        assert command[command.index(flag) + 1] == value
    evidence = json.loads(
        (tmp_path / "supervisor-config.json").read_text(encoding="utf-8")
    )
    assert evidence["measurementCommand"] == command
    assert evidence["totalFiles"] == 300_000
    assert evidence["initialFiles"] == 60_000
    assert evidence["initialPercent"] == 20
    assert evidence["overallTimeoutSeconds"] == captured["timeout"] == 20_000


@pytest.mark.parametrize("endpoint", ["list", "detail", "search", "v5_save"])
def test_endpoint_rotation_visits_every_page_or_resource_without_stride_gaps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, endpoint: str
) -> None:
    server = ProgressServer()
    requests: list[httpx.Request] = []
    observations: list[dict[str, object]] = []
    driver = make_driver(tmp_path)
    driver.pool = {
        "bookIds": [f"b{i}" for i in range(8)],
        "resourceIds": [f"r{i}" for i in range(8)],
        "formats": ["epub"] * 8,
    }
    driver.duration_seconds = 60
    driver.requests_per_second = 1_000_000
    original_client = httpx.Client

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if endpoint == "v5_save":
            return server.handle(request)
        return httpx.Response(200, json={"ok": True, "data": {}})

    def client(**kwargs):
        return original_client(transport=httpx.MockTransport(respond), **kwargs)

    def observe(record: dict[str, object]) -> None:
        observations.append(record)
        if len(observations) == 40:
            driver.abort_event.set()

    monkeypatch.setattr(precheck.httpx, "Client", client)
    monkeypatch.setattr(driver, "_append", observe)
    driver._run_endpoint(endpoint)
    assert [record["sequence"] for record in observations] == list(range(40))
    assert all(record["success"] for record in observations)
    if endpoint == "list":
        assert [int(request.url.params["page"]) for request in requests] == list(
            range(1, 21)
        ) * 2
    elif endpoint == "detail":
        assert [request.url.path for request in requests] == [
            f"/api/books/b{i}" for i in range(8)
        ] * 5
    elif endpoint == "v5_save":
        assert [request.url.path for request in requests] == [
            f"/api/reader/v5/resources/r{i}/progress" for i in range(8)
        ] * 5
        assert set(driver.acknowledged) == {f"r{i}" for i in range(8)}
    else:
        assert (
            sum(request.url.params["search"] == "Precheck" for request in requests)
            == 32
        )


def test_request_summary_preserves_exact_percentiles_errors_and_time_span(
    tmp_path: Path,
) -> None:
    path = tmp_path / "requests.jsonl"
    with path.open("w", encoding="utf-8") as stream:
        for index in range(1000, 0, -1):
            record = {
                "phase": "growth",
                "endpoint": "detail",
                "scanActive": True,
                "success": index <= 998,
                "elapsedMs": index,
                "startedMonotonic": index,
                "endedMonotonic": index + 1,
                "status": 200 if index <= 998 else 503,
            }
            stream.write(json.dumps(record) + "\n")
    (summary,) = _request_summaries(path)
    assert summary["sampleCount"] == 1000
    assert summary["successCount"] == 998
    assert summary["failureCount"] == 2
    assert summary["successRate"] == 0.998
    assert summary["observedSeconds"] == 1000
    assert summary["achievedRequestsPerSecond"] == 1
    assert summary["sampleEvidenceSufficient"] is True
    assert summary["errors"] == {"503": 2}
    assert summary["latencyMs"] == {"p50": 500, "p95": 950, "p99": 990, "max": 1000}


@pytest.mark.parametrize("field", ["startedMonotonic", "endedMonotonic"])
@pytest.mark.parametrize("value", [None, "not-a-time"])
def test_request_summary_rejects_malformed_present_timestamp(
    tmp_path: Path, field: str, value: object
) -> None:
    path = tmp_path / "requests.jsonl"
    path.write_text(
        json.dumps({"phase": "idle", "endpoint": "list", field: value}),
        encoding="utf-8",
    )
    with pytest.raises((TypeError, ValueError)):
        _request_summaries(path)


def test_markdown_omits_full_mappings_but_preserves_json_evidence(
    tmp_path: Path, integrity_library
) -> None:
    engine, _, records = integrity_library
    snapshot = _verify_scan_integrity(
        engine, "owned", records, tmp_path / "associations.json"
    )
    rescan = {
        "before": snapshot.identity,
        "after": snapshot.identity,
        "countsUnchanged": True,
    }
    summary = {
        "capturedAt": "test",
        "releaseCommit": "test",
        "dataset": precheck.dataset_summary(records),
        "requestSummaries": [],
        "rescan": rescan,
        "phases": [],
        "limitations": list(precheck.PRECHECK_LIMITATIONS),
        "evidence": {"rescanIntegrity": str(tmp_path / "rescan-integrity.json")},
    }
    precheck.write_json(tmp_path / "rescan-integrity.json", rescan)
    precheck.write_json(tmp_path / "summary.json", summary)
    original_json = (tmp_path / "summary.json").read_bytes()
    markdown = precheck._summary_markdown(summary, run_root=tmp_path)
    assert "book-owned-0" not in markdown
    assert "bookBindings" not in markdown
    assert '"bookCount": 2' in markdown
    assert "[rescan-integrity.json](rescan-integrity.json)" in markdown
    assert "Actual Web/Android/iOS media clients" in markdown
    assert "Long-duration sustained parsing/import activity is not verified" in markdown
    assert "I/O, DB lock waits" in markdown
    assert (tmp_path / "summary.json").read_bytes() == original_json
    assert summary["rescan"]["before"]["bookBindings"] == {
        "book-owned-0": "book-node-owned-0",
        "book-owned-1": "book-node-owned-1",
    }
    assert (
        json.loads((tmp_path / "rescan-integrity.json").read_text())["before"][
            "bookBindings"
        ]
        == snapshot.identity["bookBindings"]
    )
