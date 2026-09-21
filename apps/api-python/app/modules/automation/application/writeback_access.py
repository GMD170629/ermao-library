"""Revalidate a frozen file write against current grant, ownership and metadata."""

from dataclasses import dataclass
from typing import cast

from app.modules.automation.application.catalog import AutomationCatalog
from app.modules.automation.application.grants import AuthorizeAutomation
from app.modules.automation.application.settings import AutomationSettingsPort
from app.modules.automation.domain.access import AutomationAccessError, WritebackTarget
from app.modules.library.public import (
    MetadataFileTargetPort,
    MetadataPatchError,
    MetadataTarget,
)
from app.modules.metadata.public import (
    PlannedStandardWrite,
    StandardMetadataError,
    StandardWritePlan,
)


@dataclass(frozen=True)
class RecheckStandardWriteAccess:
    authorizer: AuthorizeAutomation
    settings: AutomationSettingsPort
    catalog: AutomationCatalog
    sources: MetadataFileTargetPort

    def __call__(self, plan: StandardWritePlan, target: PlannedStandardWrite) -> None:
        settings = self.settings.load()
        try:
            access = self.authorizer.operation(
                grant_id=plan.grant_id,
                user_id=plan.user_id,
                service_enabled=settings.enabled,
                enabled_scopes=settings.enabled_scopes,
            )
            access.require_writeback(
                WritebackTarget.SIDECAR
                if target.file.format in {"OPF", "ComicInfo"}
                else WritebackTarget.EMBEDDED,
                target.file.library_id,
            )
            kind = target.metadata_target_type
            if kind not in {"book", "resource", "source_node"}:
                raise StandardMetadataError("INVALID_TARGET")
            snapshot = self.catalog.metadata.snapshot(
                cast(MetadataTarget, kind),
                target.metadata_target_id,
                access.permissions.library_ids,
            )
            source = self.sources.get(
                target.source_node_id, access.permissions.library_ids
            )
            if (
                snapshot is None
                or source is None
                or snapshot.book_id != target.book_id
                or source.book_id != target.book_id
                or source.resource_id != target.resource_id
                or source.asset_id != target.asset_id
                or source.library_id != target.file.library_id
                or source.root != target.file.root
                or source.relative_path != target.source_relative_path
            ):
                raise StandardMetadataError("SOURCE_CHANGED")
            if snapshot.revision != target.metadata_revision:
                raise StandardMetadataError("METADATA_CONFLICT")
        except AutomationAccessError as error:
            raise StandardMetadataError("AUTHORIZATION_REVOKED") from error
        except MetadataPatchError as error:
            raise StandardMetadataError("SOURCE_CHANGED") from error
