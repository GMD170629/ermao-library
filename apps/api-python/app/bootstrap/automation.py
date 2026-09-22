"""Compose automation grant use cases; no request or persistence behavior."""

import logging
from collections.abc import Callable
from typing import cast
from uuid import uuid4

from sqlalchemy.orm import Session

from app.bootstrap.readable_resource_pipeline import build_readable_resource_pipeline
from app.bootstrap.reader import reader_v5_library_queries
from app.core.config import Settings, get_settings
from app.core.failure_diagnostics import RuntimeFailureDiagnostics
from app.core.time import now_timestamp_ms
from app.db.maintenance import database_maintenance_is_active
from app.modules.auth.infrastructure.automation_identity import (
    SqlAlchemyAutomationIdentity,
)
from app.modules.automation.application.catalog import AutomationCatalog
from app.modules.automation.application.deletions import AutomationDeletions
from app.modules.automation.application.execution import RecheckMutationAccess
from app.modules.automation.application.file_moves import AutomationFileMoves
from app.modules.automation.application.grants import (
    AuthorizeAutomation,
    ManageGrants,
    RecordGrantUse,
)
from app.modules.automation.application.operation_management import (
    ManageAutomationOperations,
)
from app.modules.automation.application.operations import AutomationOperations
from app.modules.automation.application.settings import ConfigureAutomation
from app.modules.automation.application.system import AutomationSystem
from app.modules.automation.application.uploads import AutomationUploads
from app.modules.automation.application.writeback_plans import BuildStandardWritePlan
from app.modules.automation.application.writebacks import AutomationWritebacks
from app.modules.automation.application.writes import AutomationWrites
from app.modules.automation.infrastructure.credentials import AutomationCredentials
from app.modules.automation.infrastructure.grants import SqlAlchemyGrantStore
from app.modules.automation.infrastructure.operation_history import (
    SqlAlchemyOperationHistory,
)
from app.modules.automation.infrastructure.receipts import SqlAlchemyReceiptStore
from app.modules.automation.infrastructure.runtime import DatabaseAutomationRuntime
from app.modules.automation.infrastructure.token_vault import AutomationTokenVault
from app.modules.automation.infrastructure.uploads import (
    SqlAlchemyUploads,
    StagedUploadFiles,
)
from app.modules.automation.presentation.mcp import AutomationMcpEndpoint
from app.modules.imports.infrastructure.automation_configuration import (
    AutomationLibraryConfiguration,
)
from app.modules.imports.infrastructure.automation_uploads import (
    ImportAttachmentUploads,
)
from app.modules.imports.infrastructure.deletion_index import DeletedSourceIndex
from app.modules.imports.infrastructure.readable_resource.filesystem import (
    OsSourceTreeFilesystem,
)
from app.modules.imports.infrastructure.readable_resource.source_node_deletion import (
    LibrarySourceNodeDeletionAdapter,
)
from app.modules.library.application.bulk_operations import (
    ExecuteBulkMetadata,
    ExecuteBulkShelfMembership,
)
from app.modules.library.application.file_deletions import FileDeletions
from app.modules.library.application.file_move_plans import PrepareFileMovePlan
from app.modules.library.application.metadata_patches import ApplyMetadataPatches
from app.modules.library.application.queries import (
    GetSmartShelfBookIds,
    SmartShelfCriteria,
)
from app.modules.library.infrastructure.automation_access import (
    SqlAlchemyVisibleLibraryIds,
)
from app.modules.library.infrastructure.automation_uploads import (
    LibraryAttachmentCovers,
)
from app.modules.library.infrastructure.bulk_operations import (
    SqlAlchemyBulkBookOperations,
)
from app.modules.library.infrastructure.catalog import SqlAlchemyCatalogQueries
from app.modules.library.infrastructure.file_deletions import (
    SqlAlchemyDeleteStore,
    StandardDeleteFiles,
)
from app.modules.library.infrastructure.file_move_operations import (
    SqlAlchemyFileMoveOperations,
)
from app.modules.library.infrastructure.metadata_file_targets import (
    SqlAlchemyMetadataFileTargets,
)
from app.modules.library.infrastructure.metadata_patches import (
    SqlAlchemyMetadataPatches,
)
from app.modules.library.infrastructure.move_inventory import AnchoredMoveInspection
from app.modules.library.infrastructure.move_topology import SqlAlchemyMoveTopology
from app.modules.library.infrastructure.persistence.source_tree_repository import (
    SqlAlchemySourceNodeRepository,
)
from app.modules.library.infrastructure.queries import SqlAlchemyLibraryQueries
from app.modules.library.infrastructure.source_file_access import (
    open_library_directory,
    open_library_file,
)
from app.modules.metadata.infrastructure.standard_files import (
    AnchoredStandardMetadataReader,
)
from app.modules.metadata.infrastructure.standard_publication import (
    StandardMetadataPublication,
)
from app.modules.metadata.infrastructure.standard_writeback_store import (
    SqlAlchemyStandardWritePlans,
)
from app.modules.shelf.application.commands import (
    CreateShelf,
    DeleteShelf,
    ShelfWriteStore,
    UpdateShelf,
)
from app.modules.shelf.application.smart_rules import normalize_smart_shelf_rules
from app.modules.shelf.infrastructure import shelves as shelf_store
from app.modules.shelf.infrastructure.catalog import SqlAlchemyCatalogShelfQueries
from app.modules.system.infrastructure.automation_audit import SqlAlchemyAutomationAudit
from app.modules.system.infrastructure.automation_management import (
    SqlAlchemyAutomationSystem,
)
from app.modules.system.infrastructure.automation_settings import (
    SqlAlchemyAutomationSettings,
)
from app.services.library_filters import normalize_filter_rules
from app.services.organize_scheduler import get_organize_policy, update_organize_policy


def build_automation_uploads(db: Session) -> AutomationUploads:
    settings = get_settings()
    return AutomationUploads(
        SqlAlchemyUploads(db),
        StagedUploadFiles(settings.resolved_storage_root),
        ImportAttachmentUploads(db, settings, open_library_directory),
        LibraryAttachmentCovers(db, settings.resolved_storage_root),
        SqlAlchemyReceiptStore(db),
        RecheckMutationAccess(
            build_automation_authorizer(db), SqlAlchemyAutomationSettings(db)
        ),
        db,
        now_timestamp_ms,
        lambda: uuid4().hex,
        RuntimeFailureDiagnostics(
            logging.getLogger(__name__), "automation", lambda: Session(db.get_bind())
        ),
    )


def build_automation_settings(db: Session) -> ConfigureAutomation:
    return ConfigureAutomation(
        SqlAlchemyAutomationSettings(db),
        SqlAlchemyAutomationIdentity(db, SqlAlchemyVisibleLibraryIds(db)),
        db,
        SqlAlchemyAutomationAudit(db),
    )


def build_grant_manager(db: Session, settings: Settings | None = None) -> ManageGrants:
    return ManageGrants(
        SqlAlchemyGrantStore(db),
        SqlAlchemyAutomationIdentity(db, SqlAlchemyVisibleLibraryIds(db)),
        AutomationCredentials(),
        db,
        now_timestamp_ms,
        SqlAlchemyAutomationAudit(db),
        AutomationTokenVault(
            (settings or get_settings()).resolved_storage_root / "secrets"
        ),
        lambda: SqlAlchemyAutomationSettings(db).load().enabled,
        lambda: SqlAlchemyAutomationSettings(db).load().enabled_scopes,
    )


def build_automation_authorizer(db: Session) -> AuthorizeAutomation:
    return AuthorizeAutomation(
        SqlAlchemyGrantStore(db),
        SqlAlchemyAutomationIdentity(db, SqlAlchemyVisibleLibraryIds(db)),
        AutomationCredentials(),
        now_timestamp_ms,
    )


def build_automation_catalog(db: Session) -> AutomationCatalog:
    smart = GetSmartShelfBookIds(
        SqlAlchemyLibraryQueries(db, reader_queries=reader_v5_library_queries(db))
    )
    return AutomationCatalog(
        SqlAlchemyVisibleLibraryIds(db),
        SqlAlchemyCatalogQueries(db),
        SqlAlchemyCatalogShelfQueries(
            db,
            lambda rules, user_id: smart.execute(
                SmartShelfCriteria.from_external(rules), user_id=user_id
            ),
        ),
        SqlAlchemyMetadataPatches(db),
        SqlAlchemySourceNodeRepository(db),
        AnchoredStandardMetadataReader(open_library_file),
    )


def build_mcp_endpoint(
    session_factory: Callable[[], Session], version: str
) -> AutomationMcpEndpoint:
    return AutomationMcpEndpoint(
        DatabaseAutomationRuntime(
            session_factory,
            SqlAlchemyAutomationSettings,
            build_automation_authorizer,
            build_automation_catalog,
            database_maintenance_is_active,
            lambda db: RecordGrantUse(SqlAlchemyGrantStore(db), db, now_timestamp_ms),
            build_automation_writes,
            build_automation_file_moves,
            build_automation_writebacks,
            build_automation_uploads,
            build_automation_system,
            build_automation_deletions,
        ),
        version,
    )


def build_automation_writes(db: Session) -> AutomationWrites:
    port = SqlAlchemyBulkBookOperations(
        db, reader_queries=reader_v5_library_queries(db)
    )
    return AutomationWrites(
        build_automation_catalog(db),
        CreateShelf(cast(ShelfWriteStore, shelf_store), db),
        ExecuteBulkShelfMembership(port, db),
        ExecuteBulkMetadata(port, db),
        SqlAlchemyReceiptStore(db),
        db,
        now_timestamp_ms,
        lambda: uuid4().hex,
        ApplyMetadataPatches(SqlAlchemyMetadataPatches(db), db),
        RecheckMutationAccess(
            build_automation_authorizer(db), SqlAlchemyAutomationSettings(db)
        ),
        UpdateShelf(cast(ShelfWriteStore, shelf_store), db),
        DeleteShelf(cast(ShelfWriteStore, shelf_store), db),
        lambda shelf_id, user_id: shelf_store.get_owned_shelf(db, shelf_id, user_id),
        lambda value: normalize_smart_shelf_rules(
            value, normalize_filter_rules=normalize_filter_rules
        ),
    )


def build_automation_file_moves(db: Session) -> AutomationFileMoves:
    return AutomationFileMoves(
        PrepareFileMovePlan(
            SqlAlchemyMoveTopology(db),
            AnchoredMoveInspection(),
            now_timestamp_ms,
            lambda: uuid4().hex,
        ),
        SqlAlchemyFileMoveOperations(db),
        SqlAlchemyReceiptStore(db),
        RecheckMutationAccess(
            build_automation_authorizer(db), SqlAlchemyAutomationSettings(db)
        ),
        db,
        now_timestamp_ms,
        lambda: uuid4().hex,
    )


def build_automation_writebacks(db: Session) -> AutomationWritebacks:
    return AutomationWritebacks(
        BuildStandardWritePlan(
            build_automation_catalog(db),
            SqlAlchemyMetadataFileTargets(db),
            StandardMetadataPublication(open_library_directory, open_library_file),
            now_timestamp_ms,
            lambda: uuid4().hex,
        ),
        SqlAlchemyStandardWritePlans(
            db, queue_capacity=get_settings().metadata_opf_queue_max_pending
        ),
        SqlAlchemyReceiptStore(db),
        RecheckMutationAccess(
            build_automation_authorizer(db), SqlAlchemyAutomationSettings(db)
        ),
        db,
        now_timestamp_ms,
        lambda: uuid4().hex,
    )


def build_automation_operation_manager(db: Session) -> ManageAutomationOperations:
    return ManageAutomationOperations(
        SqlAlchemyOperationHistory(db),
        SqlAlchemyGrantStore(db),
        SqlAlchemyAutomationIdentity(db, SqlAlchemyVisibleLibraryIds(db)),
        AutomationOperations(
            build_automation_file_moves(db),
            build_automation_writebacks(db),
            build_automation_uploads(db),
            build_automation_deletions(db),
        ),
        db,
        now_timestamp_ms,
        RuntimeFailureDiagnostics(logging.getLogger(__name__), "automation", lambda: Session(db.get_bind())),
    )


def build_automation_system(db: Session) -> AutomationSystem:
    library = AutomationLibraryConfiguration(db)
    return AutomationSystem(
        SqlAlchemyAutomationSystem(
            db,
            library.read,
            library.write,
            lambda: get_organize_policy(db),
            lambda values: update_organize_policy(db, values),
        )
    )


def build_automation_deletions(db: Session) -> AutomationDeletions:
    from_delete = LibrarySourceNodeDeletionAdapter(
        build_readable_resource_pipeline(db, get_settings()).delete_source_node
    )
    index = DeletedSourceIndex(db, from_delete.delete_source_node)
    return AutomationDeletions(
        FileDeletions(
            SqlAlchemyMoveTopology(db).deletion_source,
            SqlAlchemyDeleteStore(db),
            db,
            StandardDeleteFiles(
                get_settings().resolved_storage_root / "automation" / "delete-locks",
                OsSourceTreeFilesystem(),
            ),
            index.enqueue,
            index.status,
            now_timestamp_ms,
            lambda: uuid4().hex,
            RuntimeFailureDiagnostics(
                logging.getLogger(__name__), "library", lambda: Session(db.get_bind())
            ),
        ),
        RecheckMutationAccess(
            build_automation_authorizer(db), SqlAlchemyAutomationSettings(db)
        ),
    )
