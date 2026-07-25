from __future__ import annotations

import uuid
from collections.abc import Callable

from appv2.modules.catalog.application import CatalogReadAdapter, CatalogService
from appv2.modules.catalog.contracts import (
    CatalogEdition,
    CatalogFile,
    CatalogImport,
    CatalogImportPort,
    CatalogMetadataPort,
    CatalogReadPort,
    CatalogVolume,
    CatalogWork,
)
from appv2.modules.delivery.contracts import (
    DeliverableFile,
    DeliverableFilePort,
    DeliveryUnitOfWork,
)
from appv2.modules.discovery.contracts import DiscoveryUnitOfWork, ImportEnqueuePort
from appv2.modules.ingestion.application import IngestionService
from appv2.modules.ingestion.contracts import ImportResult, IngestionUnitOfWork
from appv2.modules.metadata.contracts import MetadataUnitOfWork
from appv2.modules.operations.contracts import (
    OperationsUnitOfWork,
    QueueOverviewPort,
    QueueSnapshot,
)


class CatalogPorts(
    CatalogReadPort,
    CatalogImportPort,
    CatalogMetadataPort,
    DeliverableFilePort,
):
    def __init__(self, *, service: CatalogService, read_adapter: CatalogReadAdapter) -> None:
        self._service = service
        self._read = read_adapter

    def get_work(self, work_id: uuid.UUID) -> CatalogWork | None:
        return self._read.get_work(work_id)

    def get_edition(self, edition_id: uuid.UUID) -> CatalogEdition | None:
        return self._read.get_edition(edition_id)

    def editions_for_work(self, work_id: uuid.UUID) -> list[CatalogEdition]:
        return self._read.editions_for_work(work_id)

    def get_file(self, file_id: uuid.UUID) -> CatalogFile | None:
        return self._read.get_file(file_id)

    def get_volume(self, volume_id: uuid.UUID) -> CatalogVolume | None:
        return self._read.get_volume(volume_id)

    def files_for_edition(self, edition_id: uuid.UUID) -> list[CatalogFile]:
        return self._read.files_for_edition(edition_id)

    def volumes_for_edition(self, edition_id: uuid.UUID) -> list[CatalogVolume]:
        return self._read.volumes_for_edition(edition_id)

    def import_file(self, imported: CatalogImport) -> CatalogEdition:
        return self._service.import_file(imported)

    def publish_conversion(
        self,
        source_edition_id: uuid.UUID,
        converted: CatalogImport,
    ) -> CatalogEdition | None:
        return self._service.publish_conversion(source_edition_id, converted)

    def apply_metadata(self, work_id: uuid.UUID, values: dict[str, object]) -> CatalogWork | None:
        return self._service.apply_metadata(work_id, values)

    def get_deliverable(self, file_id: uuid.UUID) -> DeliverableFile | None:
        file = self._read.get_file(file_id)
        if file is None:
            return None
        return DeliverableFile(
            file_id=file.id,
            name=file.original_name,
            media_type=file.media_type,
            size_bytes=file.size_bytes,
            path=file.storage_path,
            checksum=file.checksum,
        )


class IngestionEnqueueAdapter(ImportEnqueuePort):
    def __init__(self, service: IngestionService) -> None:
        self._service = service

    def enqueue_downloaded(
        self, *, path: str, requested_by: uuid.UUID, idempotency_key: str
    ) -> ImportResult:
        return self._service.enqueue(
            source_path=path,
            requested_by=requested_by,
            idempotency_key=idempotency_key,
        )


class ApplicationQueueOverview(QueueOverviewPort):
    def __init__(
        self,
        *,
        ingestion_uow: Callable[[], IngestionUnitOfWork],
        metadata_uow: Callable[[], MetadataUnitOfWork],
        discovery_uow: Callable[[], DiscoveryUnitOfWork],
        delivery_uow: Callable[[], DeliveryUnitOfWork],
        operations_uow: Callable[[], OperationsUnitOfWork],
    ) -> None:
        self._ingestion_uow = ingestion_uow
        self._metadata_uow = metadata_uow
        self._discovery_uow = discovery_uow
        self._delivery_uow = delivery_uow
        self._operations_uow = operations_uow

    def snapshots(self) -> tuple[QueueSnapshot, ...]:
        with self._ingestion_uow() as uow:
            ingestion = QueueSnapshot("ingestion", uow.ingestion.queue_counts())
        with self._metadata_uow() as uow:
            metadata = QueueSnapshot("metadata", uow.metadata.queue_counts())
        with self._discovery_uow() as uow:
            discovery = QueueSnapshot("discovery", uow.discovery.queue_counts())
        with self._delivery_uow() as uow:
            delivery = QueueSnapshot("delivery", uow.delivery.queue_counts())
        with self._operations_uow() as uow:
            backup_counts: dict[str, int] = {}
            for backup in uow.operations.list_backups():
                backup_counts[backup.status] = backup_counts.get(backup.status, 0) + 1
        return (
            ingestion,
            metadata,
            discovery,
            delivery,
            QueueSnapshot("backups", backup_counts),
        )
