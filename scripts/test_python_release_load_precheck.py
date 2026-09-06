"""Protect load evidence against lost acknowledgements and undercounted resources."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import time
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


def test_measurement_integrity_failure_reaches_cli_and_keeps_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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
        root: Path, limit: int, *, log_path: Path
    ) -> list[FileRecord]:
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
