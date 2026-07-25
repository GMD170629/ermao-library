from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from appv2.composition.worker import WorkerRuntime
from appv2.modules.delivery.application import DeliveryWorker
from appv2.modules.discovery.application import DiscoveryWorker
from appv2.modules.ingestion.application import IngestionWorker
from appv2.modules.metadata.application import MetadataWorker
from appv2.modules.operations.application import BackupWorker, RestoreService


class WorkerUnitOfWork:
    def __init__(self, repository_name: str) -> None:
        setattr(self, repository_name, MagicMock())
        self.commits = 0

    def __enter__(self) -> WorkerUnitOfWork:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        return None


def test_ingestion_worker_no_job_success_and_retry_failure() -> None:
    unit = WorkerUnitOfWork("ingestion")
    repository = unit.ingestion
    preparation = MagicMock()
    catalog = MagicMock()
    worker = IngestionWorker(
        uow_factory=lambda: unit,
        preparation=preparation,
        catalog=catalog,
        lease_seconds=60,
    )
    repository.claim_next.return_value = None
    assert worker.run_once("worker") is False

    job = SimpleNamespace(id=uuid.uuid4(), source_path="/monitor/book.epub", attempt=1)
    repository.claim_next.return_value = job
    preparation.prepare.return_value = SimpleNamespace(
        title="Book",
        author="Author",
        media_type="book",
        format="epub",
        source_path="/monitor/book.epub",
        original_name="book.epub",
        size_bytes=100,
        checksum="a" * 64,
        metadata={},
    )
    catalog.import_file.return_value = SimpleNamespace(id=uuid.uuid4())
    assert worker.run_once("worker") is True
    repository.complete.assert_called_once()

    preparation.prepare.side_effect = ValueError("invalid import")
    assert worker.run_once("worker") is True
    assert repository.fail.call_args.kwargs["retry_at"] is not None
    repository.claim_next.return_value = SimpleNamespace(
        id=uuid.uuid4(),
        source_path="/monitor/bad.epub",
        attempt=5,
    )
    assert worker.run_once("worker") is True
    assert repository.fail.call_args.kwargs["retry_at"] is None


def test_metadata_worker_no_job_success_and_retry_failure() -> None:
    unit = WorkerUnitOfWork("metadata")
    repository = unit.metadata
    providers = MagicMock()
    worker = MetadataWorker(
        uow_factory=lambda: unit,
        providers=providers,
        lease_seconds=60,
    )
    repository.list_providers.return_value = ["provider"]
    repository.claim_next.return_value = None
    assert worker.run_once("worker") is False

    job = SimpleNamespace(id=uuid.uuid4(), query="book", attempt=1, provider_id=None)
    repository.claim_next.return_value = job
    providers.search_all.return_value = ["candidate"]
    assert worker.run_once("worker") is True
    repository.save_candidates.assert_called_with(job.id, ["candidate"])

    selected_provider_id = uuid.uuid4()
    repository.list_providers.return_value = [
        SimpleNamespace(id=uuid.uuid4()),
        SimpleNamespace(id=selected_provider_id),
    ]
    selected_job = SimpleNamespace(
        id=uuid.uuid4(),
        query="selected book",
        attempt=1,
        provider_id=selected_provider_id,
    )
    repository.claim_next.return_value = selected_job
    assert worker.run_once("worker") is True
    assert providers.search_all.call_args.args[1] == [repository.list_providers.return_value[1]]

    providers.search_all.side_effect = RuntimeError("provider unavailable")
    assert worker.run_once("worker") is True
    assert repository.fail_job.call_args.kwargs["retry_at"] is not None
    repository.claim_next.return_value = SimpleNamespace(
        id=uuid.uuid4(),
        query="book",
        attempt=5,
        provider_id=None,
    )
    assert worker.run_once("worker") is True
    assert repository.fail_job.call_args.kwargs["retry_at"] is None


def test_discovery_worker_no_job_success_and_retry_failure() -> None:
    unit = WorkerUnitOfWork("discovery")
    repository = unit.discovery
    downloads = MagicMock()
    ingestion = MagicMock()
    worker = DiscoveryWorker(
        uow_factory=lambda: unit,
        downloads=downloads,
        ingestion=ingestion,
        lease_seconds=60,
    )
    repository.claim_download.return_value = None
    assert worker.run_once("worker") is False

    job = SimpleNamespace(id=uuid.uuid4(), requested_by=uuid.uuid4(), attempt=1)
    result = SimpleNamespace(id=uuid.uuid4())
    repository.claim_download.return_value = (job, result)
    downloads.download.return_value = "/storage/download.epub"
    assert worker.run_once("worker") is True
    ingestion.enqueue_downloaded.assert_called_once()
    repository.complete_download.assert_called_with(job.id, "/storage/download.epub")

    downloads.download.side_effect = RuntimeError("download failed")
    assert worker.run_once("worker") is True
    assert repository.fail_download.call_args.kwargs["retry_at"] is not None
    repository.claim_download.return_value = (
        SimpleNamespace(id=uuid.uuid4(), requested_by=uuid.uuid4(), attempt=5),
        result,
    )
    assert worker.run_once("worker") is True
    assert repository.fail_download.call_args.kwargs["retry_at"] is None


def test_delivery_worker_no_job_success_and_retry_failure() -> None:
    unit = WorkerUnitOfWork("delivery")
    repository = unit.delivery
    files = MagicMock()
    smtp = MagicMock()
    worker = DeliveryWorker(
        uow_factory=lambda: unit,
        files=files,
        smtp=smtp,
        lease_seconds=60,
    )
    repository.claim_next.return_value = None
    assert worker.run_once("worker") is False

    job = SimpleNamespace(
        id=uuid.uuid4(),
        requested_by=uuid.uuid4(),
        file_id=uuid.uuid4(),
        recipient="reader@example.com",
        subject="Book",
        attempt=1,
    )
    repository.claim_next.return_value = job
    repository.smtp_configuration.return_value = SimpleNamespace(host="smtp.example.com")
    files.get_deliverable.return_value = SimpleNamespace(id=job.file_id)
    assert worker.run_once("worker") is True
    smtp.send.assert_called_once()
    repository.complete.assert_called_with(job.id)

    files.get_deliverable.return_value = None
    assert worker.run_once("worker") is True
    assert repository.fail.call_args.kwargs["retry_at"] is not None
    repository.claim_next.return_value = SimpleNamespace(
        id=uuid.uuid4(),
        requested_by=uuid.uuid4(),
        file_id=uuid.uuid4(),
        recipient="reader@example.com",
        subject="Book",
        attempt=5,
    )
    assert worker.run_once("worker") is True
    assert repository.fail.call_args.kwargs["retry_at"] is None


def test_backup_and_restore_workers_cover_success_and_failure() -> None:
    unit = WorkerUnitOfWork("operations")
    repository = unit.operations
    executor = MagicMock()
    backup_worker = BackupWorker(uow_factory=lambda: unit, executor=executor)
    repository.claim_backup.return_value = None
    assert backup_worker.run_once() is False
    backup = SimpleNamespace(id=uuid.uuid4())
    repository.claim_backup.return_value = backup
    executor.create.return_value = ("checksum", 1024)
    assert backup_worker.run_once() is True
    repository.complete_backup.assert_called_with(
        backup.id,
        checksum="checksum",
        size_bytes=1024,
    )
    executor.create.side_effect = RuntimeError("pg_dump failed")
    assert backup_worker.run_once() is True
    repository.fail_backup.assert_called_with(backup.id, "pg_dump failed")

    inbox = MagicMock()
    restore_executor = MagicMock()
    restore = RestoreService(
        uow_factory=lambda: unit,
        inbox=inbox,
        executor=restore_executor,
    )
    inbox.next_request.return_value = None
    assert restore.run_once() is False
    request = SimpleNamespace(request_id="restore", backup_id=backup.id)
    inbox.next_request.return_value = request
    assert restore.run_once() is True
    repository.complete_restore.assert_called_with(backup.id)
    inbox.complete.assert_called_with(request)
    restore_executor.execute.side_effect = RuntimeError("pg_restore failed")
    with pytest.raises(RuntimeError, match="pg_restore failed"):
        restore.run_once()
    inbox.fail.assert_called_with(request, "pg_restore failed")


def test_worker_runtime_invokes_every_queue_without_short_circuiting() -> None:
    container = MagicMock()
    container.ingestion_worker.run_once.return_value = False
    container.metadata_worker.run_once.return_value = True
    container.discovery_worker.run_once.return_value = False
    container.delivery_worker.run_once.return_value = True
    container.backup_worker.run_once.return_value = False
    runtime = WorkerRuntime(container=container, worker_id="worker")
    assert runtime.run_once() is True
    container.ingestion_worker.run_once.assert_called_once_with("worker")
    container.metadata_worker.run_once.assert_called_once_with("worker")
    container.discovery_worker.run_once.assert_called_once_with("worker")
    container.delivery_worker.run_once.assert_called_once_with("worker")
    container.backup_worker.run_once.assert_called_once_with()
