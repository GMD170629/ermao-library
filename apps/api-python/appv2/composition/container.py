from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from appv2.composition.adapters import (
    ApplicationQueueOverview,
    CatalogPorts,
    IngestionEnqueueAdapter,
)
from appv2.modules.accounts.api import AccountDependency
from appv2.modules.accounts.application import AccountService
from appv2.modules.accounts.infrastructure.password_reset import LocalPasswordResetNotice
from appv2.modules.accounts.infrastructure.repositories import accounts_uow_factory
from appv2.modules.catalog.application import CatalogReadAdapter, CatalogService
from appv2.modules.catalog.infrastructure.covers import LocalCoverStorage
from appv2.modules.catalog.infrastructure.repositories import catalog_uow_factory
from appv2.modules.delivery.application import DeliveryService, DeliveryWorker
from appv2.modules.delivery.infrastructure.crypto import SecretCipher
from appv2.modules.delivery.infrastructure.repositories import delivery_uow_factory
from appv2.modules.delivery.infrastructure.smtp import SmtpAdapter
from appv2.modules.discovery.application import DiscoveryService, DiscoveryWorker
from appv2.modules.discovery.infrastructure.adapters import (
    HttpDownloadAdapter,
    JsonHttpSourceSearch,
)
from appv2.modules.discovery.infrastructure.repositories import discovery_uow_factory
from appv2.modules.ingestion.application import IngestionService, IngestionWorker
from appv2.modules.ingestion.infrastructure.files import (
    LocalImportPreparation,
    LocalTextToEpubConversion,
    MonitorFileDiscovery,
    V2UploadStorage,
)
from appv2.modules.ingestion.infrastructure.repositories import ingestion_uow_factory
from appv2.modules.metadata.application import MetadataService, MetadataWorker
from appv2.modules.metadata.infrastructure.providers import ConfiguredProviderRegistry
from appv2.modules.metadata.infrastructure.repositories import metadata_uow_factory
from appv2.modules.operations.application import (
    BackupWorker,
    OperationsService,
    RestoreService,
)
from appv2.modules.operations.infrastructure.backup import (
    FileRestoreControl,
    PgBackupExecutor,
)
from appv2.modules.operations.infrastructure.health import DatabaseHealth, StorageHealth
from appv2.modules.operations.infrastructure.repositories import operations_uow_factory
from appv2.modules.operations.infrastructure.restore import (
    FileRestoreInbox,
    PgRestoreExecutor,
)
from appv2.modules.reading.application import ReadingService
from appv2.modules.reading.infrastructure.repositories import reading_uow_factory
from appv2.modules.reading.infrastructure.resources import LocalReaderResources
from appv2.modules.reporting.application import ReportingService
from appv2.modules.reporting.infrastructure.queries import SqlReportingQueries
from appv2.platform.auth import PasswordHasher
from appv2.platform.config import Settings, get_settings
from appv2.platform.database import Database
from appv2.platform.filesystem import StorageLayout

ALEMBIC_REVISION = "0001_appv2_initial"


@dataclass(slots=True)
class Container:
    settings: Settings
    database: Database
    accounts: AccountService
    current_account: AccountDependency
    catalog: CatalogService
    ingestion: IngestionService
    metadata: MetadataService
    reading: ReadingService
    discovery: DiscoveryService
    delivery: DeliveryService
    operations: OperationsService
    reporting: ReportingService
    ingestion_worker: IngestionWorker
    metadata_worker: MetadataWorker
    discovery_worker: DiscoveryWorker
    delivery_worker: DeliveryWorker
    backup_worker: BackupWorker
    restore_service: RestoreService

    def close(self) -> None:
        self.database.dispose()


def build_container(settings: Settings | None = None) -> Container:
    resolved = settings or get_settings()
    storage = StorageLayout(resolved.v2_storage_root)
    storage.ensure()
    database = Database(resolved.database_dsn)

    accounts_uow = accounts_uow_factory(database.session_factory)
    catalog_uow = catalog_uow_factory(database.session_factory)
    ingestion_uow = ingestion_uow_factory(database.session_factory)
    metadata_uow = metadata_uow_factory(database.session_factory)
    reading_uow = reading_uow_factory(database.session_factory)
    discovery_uow = discovery_uow_factory(database.session_factory)
    cipher = SecretCipher(resolved.session_secret.get_secret_value())
    delivery_uow = delivery_uow_factory(database.session_factory, cipher)
    operations_uow = operations_uow_factory(database.session_factory)

    accounts = AccountService(
        uow_factory=accounts_uow,
        password_hasher=PasswordHasher(),
        session_secret=resolved.session_secret.get_secret_value(),
        session_ttl_seconds=resolved.session_ttl_seconds,
        password_reset_notice=LocalPasswordResetNotice(storage.control),
        password_reset_ttl_seconds=resolved.password_reset_ttl_seconds,
    )
    current_account = AccountDependency(accounts)
    catalog = CatalogService(catalog_uow, LocalCoverStorage(storage.covers))
    catalog_read = CatalogReadAdapter(catalog_uow)
    catalog_ports = CatalogPorts(service=catalog, read_adapter=catalog_read)

    ingestion = IngestionService(
        uow_factory=ingestion_uow,
        discovery=MonitorFileDiscovery(resolved.monitor_root),
        uploads=V2UploadStorage(storage.temp),
        catalog=catalog_ports,
    )
    ingestion_queue = IngestionEnqueueAdapter(ingestion)
    ingestion_worker = IngestionWorker(
        uow_factory=ingestion_uow,
        preparation=LocalImportPreparation(),
        conversion=LocalTextToEpubConversion(storage.conversions),
        catalog=catalog_ports,
        lease_seconds=resolved.worker_lease_seconds,
    )

    metadata = MetadataService(
        uow_factory=metadata_uow,
        catalog=catalog_ports,
        catalog_read=catalog_ports,
    )
    metadata_worker = MetadataWorker(
        uow_factory=metadata_uow,
        providers=ConfiguredProviderRegistry(resolved.external_http_timeout_seconds),
        lease_seconds=resolved.worker_lease_seconds,
    )
    allowed_resource_roots = [resolved.v2_storage_root]
    if resolved.monitor_root is not None:
        allowed_resource_roots.append(resolved.monitor_root)
    reading = ReadingService(
        uow_factory=reading_uow,
        catalog=catalog_ports,
        resources=LocalReaderResources(
            allowed_roots=tuple(allowed_resource_roots),
            streams_per_user=resolved.file_streams_per_user_limit,
        ),
    )

    discovery = DiscoveryService(
        uow_factory=discovery_uow,
        search_port=JsonHttpSourceSearch(resolved.external_http_timeout_seconds),
    )
    discovery_worker = DiscoveryWorker(
        uow_factory=discovery_uow,
        downloads=HttpDownloadAdapter(storage.temp, resolved.external_http_timeout_seconds),
        ingestion=ingestion_queue,
        lease_seconds=resolved.worker_lease_seconds,
    )

    smtp = SmtpAdapter(resolved.smtp_timeout_seconds)
    delivery = DeliveryService(
        uow_factory=delivery_uow,
        files=catalog_ports,
        smtp=smtp,
    )
    delivery_worker = DeliveryWorker(
        uow_factory=delivery_uow,
        files=catalog_ports,
        smtp=smtp,
        lease_seconds=resolved.worker_lease_seconds,
    )

    backup_executor = PgBackupExecutor(
        database_url=resolved.database_dsn,
        backups_root=storage.backups,
    )
    operations = OperationsService(
        uow_factory=operations_uow,
        health_contributors=(
            DatabaseHealth(database.engine),
            StorageHealth(storage.root),
        ),
        queues=ApplicationQueueOverview(
            ingestion_uow=ingestion_uow,
            metadata_uow=metadata_uow,
            discovery_uow=discovery_uow,
            delivery_uow=delivery_uow,
            operations_uow=operations_uow,
        ),
        backup_executor=backup_executor,
        restore_control=FileRestoreControl(
            control_root=storage.control,
            backups_root=storage.backups,
        ),
        app_version=resolved.app_version,
        alembic_revision=ALEMBIC_REVISION,
    )
    backup_worker = BackupWorker(
        uow_factory=operations_uow,
        executor=backup_executor,
    )
    backend_root = Path(__file__).resolve().parents[2]
    restore_service = RestoreService(
        uow_factory=operations_uow,
        inbox=FileRestoreInbox(storage.control),
        executor=PgRestoreExecutor(
            database_url=resolved.database_dsn,
            backups_root=storage.backups,
            backend_root=backend_root,
            expected_version=resolved.app_version,
        ),
    )
    reporting = ReportingService(SqlReportingQueries(database.engine))

    return Container(
        settings=resolved,
        database=database,
        accounts=accounts,
        current_account=current_account,
        catalog=catalog,
        ingestion=ingestion,
        metadata=metadata,
        reading=reading,
        discovery=discovery,
        delivery=delivery,
        operations=operations,
        reporting=reporting,
        ingestion_worker=ingestion_worker,
        metadata_worker=metadata_worker,
        discovery_worker=discovery_worker,
        delivery_worker=delivery_worker,
        backup_worker=backup_worker,
        restore_service=restore_service,
    )
