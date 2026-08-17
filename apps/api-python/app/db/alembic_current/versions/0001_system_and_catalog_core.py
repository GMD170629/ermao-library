"""Create the immutable current system and catalog core schema.

This revision deliberately owns a migration-local SQLAlchemy schema.  It does
not import the runtime ORM registry, application services, or any retired
schema helpers.  The current lineage is fresh-install only; later revisions
may extend this metadata but this revision must never be edited in place.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from alembic import context, op
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    and_,
    func,
    or_,
)
from sqlalchemy.schema import SchemaItem
from sqlalchemy.sql.functions import FunctionElement

revision: str = "0001_system_and_catalog_core"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

metadata = MetaData()
_ID = String(191)
_DT = DateTime(timezone=True)


def _enum(name: str, *values: str) -> Enum:
    return Enum(*values, name=name, native_enum=False, create_constraint=True)


def _created() -> FunctionElement[datetime]:
    return func.current_timestamp()


def _table(name: str, *items: SchemaItem) -> Table:
    return Table(name, metadata, *items)


system_instance = _table(
    "SystemInstance",
    # Runtime TimestampMilliseconds is represented by its persisted BIGINT.
    # The ORM supplies the Python-side creation default.
    Column("id", Integer, primary_key=True, default=1),
    Column("createdAt", BigInteger, nullable=False),
    Column("identityBootstrapCompletedAt", BigInteger),
)
system_instance.append_constraint(
    CheckConstraint(system_instance.c.id == 1, name="SystemInstance_singleton_ck")
)

user = _table(
    "User",
    Column("id", _ID, primary_key=True),
    Column("authzVersion", Integer, nullable=False, default=1, server_default="1"),
    Column("displayName", _ID, nullable=False),
    Column("role", String(32), nullable=False, default="admin", server_default="admin"),
    Column(
        "status", String(32), nullable=False, default="active", server_default="active"
    ),
    Column("createdAt", BigInteger, nullable=False),
    Column("updatedAt", BigInteger, nullable=False),
)
user.append_constraint(
    CheckConstraint(user.c.authzVersion > 0, name="User_authzVersion_positive_ck")
)

auth_identity = _table(
    "AuthIdentity",
    Column("id", _ID, primary_key=True),
    Column("userId", _ID, nullable=False),
    Column("provider", String(32), nullable=False),
    Column("subject", String(191), nullable=False),
    Column("passwordHash", String(255)),
    Column("createdAt", BigInteger, nullable=False),
    Column("updatedAt", BigInteger, nullable=False),
    ForeignKeyConstraint(["userId"], ["User.id"], ondelete="CASCADE"),
    UniqueConstraint("provider", "subject", name="AuthIdentity_provider_subject_key"),
    Index("AuthIdentity_userId_idx", "userId"),
)

session = _table(
    "Session",
    Column("id", _ID, primary_key=True),
    Column("userId", _ID, nullable=False),
    Column("tokenHash", String(128), nullable=False),
    Column("expiresAt", BigInteger, nullable=False),
    Column("createdAt", BigInteger, nullable=False),
    Column("updatedAt", BigInteger, nullable=False),
    ForeignKeyConstraint(["userId"], ["User.id"], ondelete="CASCADE"),
    Index("Session_userId_idx", "userId"),
)

catalog_library = _table(
    "CatalogLibrary",
    Column("id", _ID, primary_key=True),
    Column("name", Text, nullable=False),
    Column("rootPath", Text, nullable=False),
    Column("rootPathKey", Text, nullable=False),
    Column(
        "organizationMode",
        _enum("organizationmode", "FLAT", "VOLUMES", "AUDIOBOOK"),
        nullable=False,
    ),
    Column("topologyVersion", Integer, nullable=False, default=1),
    Column(
        "pathComparison",
        _enum("pathcomparison", "SENSITIVE", "INSENSITIVE"),
        nullable=False,
    ),
    Column(
        "writePolicy", _enum("writepolicy", "READ_ONLY", "READ_WRITE"), nullable=False
    ),
    Column(
        "controlState",
        _enum(
            "librarycontrolstate", "DRAFT", "ACTIVATING", "ACTIVE", "PAUSED", "REMOVING"
        ),
        nullable=False,
    ),
    Column(
        "observedHealth",
        _enum("libraryhealth", "UNKNOWN", "HEALTHY", "UNAVAILABLE", "ERROR"),
        nullable=False,
    ),
    Column("configRevision", Integer, nullable=False, default=1),
    Column("topologyWriterFence", BigInteger, nullable=False, default=0),
    Column("sourceMutationFence", BigInteger, nullable=False, default=0),
    Column("nextScanGeneration", BigInteger, nullable=False, default=1),
    Column("lastSuccessfulGeneration", BigInteger),
    Column("lastSuccessfulScanAt", _DT),
    Column("createdAt", _DT, nullable=False, server_default=_created()),
    Column("updatedAt", _DT, nullable=False, server_default=_created()),
    UniqueConstraint("rootPathKey", name="CatalogLibrary_rootPathKey_key"),
)
catalog_library.append_constraint(
    CheckConstraint(
        catalog_library.c.topologyVersion > 0,
        name="CatalogLibrary_topology_version_ck",
    )
)
catalog_library.append_constraint(
    CheckConstraint(
        catalog_library.c.configRevision > 0,
        name="CatalogLibrary_config_revision_ck",
    )
)
catalog_library.append_constraint(
    CheckConstraint(
        catalog_library.c.topologyWriterFence >= 0,
        name="CatalogLibrary_writer_fence_ck",
    )
)
catalog_library.append_constraint(
    CheckConstraint(
        catalog_library.c.sourceMutationFence >= 0,
        name="CatalogLibrary_mutation_fence_ck",
    )
)
catalog_library.append_constraint(
    CheckConstraint(
        catalog_library.c.nextScanGeneration > 0,
        name="CatalogLibrary_scan_generation_ck",
    )
)

library_ignore_rule = _table(
    "LibraryIgnoreRule",
    Column("id", _ID, primary_key=True),
    Column("libraryId", _ID, nullable=False),
    Column("ruleKey", Text, nullable=False),
    Column("pattern", Text, nullable=False),
    Column("kind", _enum("ignorerulekind", "NAME", "PATH"), nullable=False),
    Column("enabled", Boolean, nullable=False, default=True),
    Column("configRevision", BigInteger, nullable=False, default=1),
    Column("createdAt", _DT, nullable=False, server_default=_created()),
    Column("updatedAt", _DT, nullable=False, server_default=_created()),
    ForeignKeyConstraint(["libraryId"], ["CatalogLibrary.id"], ondelete="CASCADE"),
    UniqueConstraint("libraryId", "ruleKey", name="LibraryIgnoreRule_library_rule_key"),
    Index("LibraryIgnoreRule_library_enabled_idx", "libraryId", "enabled"),
)

user_library_grant = _table(
    "UserLibraryGrant",
    Column("userId", _ID, primary_key=True),
    Column("libraryId", _ID, primary_key=True),
    Column("level", _enum("grantlevel", "READ", "CURATE", "ADMIN"), nullable=False),
    Column("scopeEpoch", BigInteger, nullable=False, default=1),
    Column("createdAt", _DT, nullable=False, server_default=_created()),
    Column("updatedAt", _DT, nullable=False, server_default=_created()),
    ForeignKeyConstraint(["userId"], ["User.id"], ondelete="CASCADE"),
    ForeignKeyConstraint(["libraryId"], ["CatalogLibrary.id"], ondelete="CASCADE"),
    UniqueConstraint("userId", "libraryId", name="UserLibraryGrant_user_library_key"),
    Index("UserLibraryGrant_library_level_idx", "libraryId", "level"),
)

library_root_registry_lock = _table(
    "LibraryRootRegistryLock",
    Column("id", Integer, primary_key=True, default=1),
    Column("ownerToken", _ID),
    Column("fence", BigInteger, nullable=False, default=0),
    Column("leaseExpiresAt", _DT),
    Column("heartbeatAt", _DT),
    Column("updatedAt", _DT, nullable=False, server_default=_created()),
)
library_root_registry_lock.append_constraint(
    CheckConstraint(
        library_root_registry_lock.c.id == 1,
        name="LibraryRootRegistryLock_singleton_ck",
    )
)

library_work = _table(
    "LibraryWork",
    Column("id", _ID, primary_key=True),
    Column("libraryId", _ID, nullable=False),
    Column("metadataRevision", BigInteger, nullable=False, default=0),
    Column("createdAt", _DT, nullable=False, server_default=_created()),
    Column("updatedAt", _DT, nullable=False, server_default=_created()),
    ForeignKeyConstraint(["libraryId"], ["CatalogLibrary.id"], ondelete="CASCADE"),
    UniqueConstraint("libraryId", "id", name="LibraryWork_library_id_key"),
)

work_version = _table(
    "WorkVersion",
    Column("id", _ID, primary_key=True),
    Column("libraryId", _ID, nullable=False),
    Column("metadataRevision", BigInteger, nullable=False, default=0),
    Column("createdAt", _DT, nullable=False, server_default=_created()),
    Column("updatedAt", _DT, nullable=False, server_default=_created()),
    ForeignKeyConstraint(["libraryId"], ["CatalogLibrary.id"], ondelete="CASCADE"),
    UniqueConstraint("libraryId", "id", name="WorkVersion_library_id_key"),
)

library_volume = _table(
    "LibraryVolume",
    Column("id", _ID, primary_key=True),
    Column("libraryId", _ID, nullable=False),
    Column("readingMorphology", String(32), nullable=False),
    Column("contentState", String(32), nullable=False),
    Column("contentRevision", BigInteger, nullable=False, default=0),
    Column("requiredManifestRevision", BigInteger, nullable=False, default=0),
    Column("optionalManifestRevision", BigInteger, nullable=False, default=0),
    Column("metadataRevision", BigInteger, nullable=False, default=0),
    Column("requiredManifestDigest", String(191)),
    Column("publicationFingerprint", String(191)),
    Column("createdAt", _DT, nullable=False, server_default=_created()),
    Column("updatedAt", _DT, nullable=False, server_default=_created()),
    ForeignKeyConstraint(["libraryId"], ["CatalogLibrary.id"], ondelete="CASCADE"),
    UniqueConstraint("libraryId", "id", name="LibraryVolume_library_id_key"),
)

volume_asset = _table(
    "VolumeAsset",
    Column("id", _ID, primary_key=True),
    Column("libraryId", _ID, nullable=False),
    Column("sourceFormat", String(64), nullable=False),
    Column("mimeType", String(191)),
    Column("sizeBytes", BigInteger),
    Column("contentDigest", String(191)),
    Column("embeddedTrackNumber", Integer),
    Column(
        "validationState",
        _enum("assetvalidationstate", "PENDING", "READY", "UNREADABLE"),
        nullable=False,
    ),
    Column("createdAt", _DT, nullable=False, server_default=_created()),
    Column("updatedAt", _DT, nullable=False, server_default=_created()),
    ForeignKeyConstraint(["libraryId"], ["CatalogLibrary.id"], ondelete="CASCADE"),
    UniqueConstraint("libraryId", "id", name="VolumeAsset_library_id_key"),
)

library_source_entry = _table(
    "LibrarySourceEntry",
    Column("id", _ID, primary_key=True),
    Column("libraryId", _ID, nullable=False),
    Column("parentEntryId", _ID),
    Column("localName", Text, nullable=False),
    Column("localNameKey", Text, nullable=False),
    Column(
        "entryType",
        _enum("sourceentrytype", "SYNTHETIC_ROOT", "DIRECTORY", "FILE"),
        nullable=False,
    ),
    Column("filesystemIdentity", String(191)),
    Column("sizeBytes", BigInteger),
    Column("modifiedNs", BigInteger),
    Column("lastSeenGeneration", BigInteger),
    Column("absenceConfirmedAt", _DT),
    Column("childrenPresenceEpoch", BigInteger, nullable=False, default=0),
    Column("observedParentPresenceEpoch", BigInteger),
    Column("layoutState", _enum("layoutstate", "PRESENT", "INVALID"), nullable=False),
    Column("slotState", _enum("slotstate", "ACTIVE", "RETIRED"), nullable=False),
    Column("createdAt", _DT, nullable=False, server_default=_created()),
    Column("updatedAt", _DT, nullable=False, server_default=_created()),
    ForeignKeyConstraint(["libraryId"], ["CatalogLibrary.id"], ondelete="CASCADE"),
    ForeignKeyConstraint(
        ["libraryId", "parentEntryId"],
        ["LibrarySourceEntry.libraryId", "LibrarySourceEntry.id"],
        ondelete="CASCADE",
    ),
    UniqueConstraint("libraryId", "id", name="LibrarySourceEntry_library_id_key"),
)

library_source_entry.append_constraint(
    CheckConstraint(
        or_(
            library_source_entry.c.entryType != "SYNTHETIC_ROOT",
            and_(
                library_source_entry.c.parentEntryId.is_(None),
                library_source_entry.c.localName == "$root",
            ),
        ),
        name="LibrarySourceEntry_root_shape_ck",
    )
)
library_source_entry.append_constraint(
    CheckConstraint(
        or_(
            library_source_entry.c.entryType == "SYNTHETIC_ROOT",
            library_source_entry.c.parentEntryId.is_not(None),
        ),
        name="LibrarySourceEntry_parent_required_ck",
    )
)

Index(
    "LibrarySourceEntry_one_root_idx",
    library_source_entry.c.libraryId,
    unique=True,
    sqlite_where=library_source_entry.c.entryType == "SYNTHETIC_ROOT",
)
Index(
    "LibrarySourceEntry_active_slot_idx",
    library_source_entry.c.libraryId,
    library_source_entry.c.parentEntryId,
    library_source_entry.c.localNameKey,
    unique=True,
    sqlite_where=library_source_entry.c.slotState == "ACTIVE",
)

source_attachment = _table(
    "SourceAttachment",
    Column("id", _ID, primary_key=True),
    Column("libraryId", _ID, nullable=False),
    Column("sourceEntryId", _ID, nullable=False),
    Column("workId", _ID),
    Column("versionId", _ID),
    Column("volumeId", _ID),
    Column(
        "role", _enum("attachmentrole", "COVER", "OPF", "CUE", "LRC"), nullable=False
    ),
    Column("sourceFormat", String(64)),
    Column("createdAt", _DT, nullable=False, server_default=_created()),
    ForeignKeyConstraint(["libraryId"], ["CatalogLibrary.id"], ondelete="CASCADE"),
    ForeignKeyConstraint(
        ["libraryId", "sourceEntryId"],
        ["LibrarySourceEntry.libraryId", "LibrarySourceEntry.id"],
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["libraryId", "workId"],
        ["LibraryWork.libraryId", "LibraryWork.id"],
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["libraryId", "versionId"],
        ["WorkVersion.libraryId", "WorkVersion.id"],
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["libraryId", "volumeId"],
        ["LibraryVolume.libraryId", "LibraryVolume.id"],
        ondelete="CASCADE",
    ),
    UniqueConstraint("libraryId", "sourceEntryId", name="SourceAttachment_entry_key"),
)
source_attachment.append_constraint(
    CheckConstraint(
        (
            source_attachment.c.workId.is_not(None).cast(Integer)
            + source_attachment.c.versionId.is_not(None).cast(Integer)
            + source_attachment.c.volumeId.is_not(None).cast(Integer)
            == 1
        ),
        name="SourceAttachment_one_owner_ck",
    )
)

library_scan_run = _table(
    "LibraryScanRun",
    Column("id", _ID, primary_key=True),
    Column("libraryId", _ID, nullable=False),
    Column("generation", BigInteger, nullable=False),
    Column("configRevision", BigInteger, nullable=False),
    Column(
        "modeSnapshot",
        _enum("organizationmode", "FLAT", "VOLUMES", "AUDIOBOOK"),
        nullable=False,
    ),
    Column("topologyVersionSnapshot", Integer, nullable=False),
    Column("rootIdentitySnapshot", String(191)),
    Column("topologyWriterFence", BigInteger, nullable=False),
    Column(
        "state",
        _enum("scanstate", "PENDING", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"),
        nullable=False,
    ),
    Column("leaseOwner", _ID),
    Column("leaseExpiresAt", _DT),
    Column("heartbeatAt", _DT),
    Column(
        "stage", _enum("scanstage", "DISCOVER", "RECONCILE", "FINALIZE"), nullable=False
    ),
    Column("discoveredCount", BigInteger, nullable=False, default=0),
    Column("diagnosticCount", BigInteger, nullable=False, default=0),
    Column("startedAt", _DT),
    Column("finishedAt", _DT),
    Column("createdByUserId", _ID),
    Column("createdAt", _DT, nullable=False, server_default=_created()),
    ForeignKeyConstraint(["libraryId"], ["CatalogLibrary.id"], ondelete="CASCADE"),
    ForeignKeyConstraint(["createdByUserId"], ["User.id"], ondelete="SET NULL"),
    UniqueConstraint("libraryId", "id", name="LibraryScanRun_library_id_key"),
    UniqueConstraint(
        "libraryId", "generation", name="LibraryScanRun_library_generation_key"
    ),
    Index("LibraryScanRun_library_state_idx", "libraryId", "state"),
)

library_scan_work_item = _table(
    "LibraryScanWorkItem",
    Column("id", _ID, primary_key=True),
    Column("libraryId", _ID, nullable=False),
    Column("scanRunId", _ID, nullable=False),
    Column("subtreeRootEntryId", _ID),
    Column("scopeRelativePath", Text, nullable=False),
    Column(
        "state",
        _enum("scanstate", "PENDING", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"),
        nullable=False,
    ),
    Column(
        "stage", _enum("scanstage", "DISCOVER", "RECONCILE", "FINALIZE"), nullable=False
    ),
    Column("leaseOwner", _ID),
    Column("leaseExpiresAt", _DT),
    Column("attempt", Integer, nullable=False, default=0),
    Column("availableAt", _DT, nullable=False, server_default=_created()),
    Column("idempotencyKey", String(191), nullable=False),
    Column("discoveredCount", BigInteger, nullable=False, default=0),
    Column("createdAt", _DT, nullable=False, server_default=_created()),
    ForeignKeyConstraint(
        ["libraryId", "scanRunId"],
        ["LibraryScanRun.libraryId", "LibraryScanRun.id"],
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["libraryId", "subtreeRootEntryId"],
        ["LibrarySourceEntry.libraryId", "LibrarySourceEntry.id"],
        ondelete="CASCADE",
    ),
    UniqueConstraint("libraryId", "id", name="LibraryScanWorkItem_library_id_key"),
    UniqueConstraint(
        "libraryId", "idempotencyKey", name="LibraryScanWorkItem_idempotency_key"
    ),
    Index("LibraryScanWorkItem_lease_idx", "libraryId", "state", "availableAt"),
)

path_collision_observation = _table(
    "PathCollisionObservation",
    Column("id", _ID, primary_key=True),
    Column("libraryId", _ID, nullable=False),
    Column("scanRunId", _ID, nullable=False),
    Column("parentEntryId", _ID, nullable=False),
    Column("localName", Text, nullable=False),
    Column("localNameKey", Text, nullable=False),
    Column("evidence", JSON, nullable=False, default=dict),
    Column("observedAt", _DT, nullable=False, server_default=_created()),
    ForeignKeyConstraint(
        ["libraryId", "scanRunId"],
        ["LibraryScanRun.libraryId", "LibraryScanRun.id"],
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["libraryId", "parentEntryId"],
        ["LibrarySourceEntry.libraryId", "LibrarySourceEntry.id"],
        ondelete="CASCADE",
    ),
    UniqueConstraint(
        "libraryId",
        "scanRunId",
        "parentEntryId",
        "localNameKey",
        "localName",
        name="PathCollisionObservation_scan_slot_key",
    ),
)

layout_diagnostic = _table(
    "LayoutDiagnostic",
    Column("id", _ID, primary_key=True),
    Column("libraryId", _ID, nullable=False),
    Column("scanRunId", _ID),
    Column("generation", BigInteger, nullable=False),
    Column("configRevision", BigInteger, nullable=False),
    Column("scopeRelativePath", Text, nullable=False),
    Column("code", String(96), nullable=False),
    Column("severity", String(32), nullable=False),
    Column("parameters", JSON, nullable=False, default=dict),
    Column("firstObservedAt", _DT, nullable=False, server_default=_created()),
    Column("lastObservedAt", _DT, nullable=False, server_default=_created()),
    Column("resolvedAt", _DT),
    ForeignKeyConstraint(["libraryId"], ["CatalogLibrary.id"], ondelete="CASCADE"),
    ForeignKeyConstraint(
        ["libraryId", "scanRunId"],
        ["LibraryScanRun.libraryId", "LibraryScanRun.id"],
        ondelete="CASCADE",
    ),
    Index(
        "LayoutDiagnostic_library_generation_idx",
        "libraryId",
        "generation",
        "scopeRelativePath",
    ),
)

topology_unit = _table(
    "TopologyUnit",
    Column("id", _ID, primary_key=True),
    Column("libraryId", _ID, nullable=False),
    Column(
        "unitKind",
        _enum(
            "topologyunitkind",
            "WORK_CONTAINER",
            "AUDIOBOOK_WORK",
            "VERSION_CONTAINER",
            "FLAT_VOLUME",
            "SINGLE_FILE_VOLUME",
            "MULTI_ASSET_VOLUME",
        ),
        nullable=False,
    ),
    Column("workOwnerId", _ID),
    Column("versionOwnerId", _ID),
    Column("volumeOwnerId", _ID),
    Column("activeRevisionId", _ID),
    Column("createdAt", _DT, nullable=False, server_default=_created()),
    ForeignKeyConstraint(["libraryId"], ["CatalogLibrary.id"], ondelete="CASCADE"),
    ForeignKeyConstraint(
        ["libraryId", "workOwnerId"],
        ["LibraryWork.libraryId", "LibraryWork.id"],
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["libraryId", "versionOwnerId"],
        ["WorkVersion.libraryId", "WorkVersion.id"],
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["libraryId", "volumeOwnerId"],
        ["LibraryVolume.libraryId", "LibraryVolume.id"],
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["libraryId", "id", "activeRevisionId"],
        [
            "TopologyUnitRevision.libraryId",
            "TopologyUnitRevision.unitId",
            "TopologyUnitRevision.id",
        ],
        ondelete="RESTRICT",
    ),
    UniqueConstraint("libraryId", "id", name="TopologyUnit_library_id_key"),
)

topology_unit.append_constraint(
    CheckConstraint(
        (
            topology_unit.c.workOwnerId.is_not(None).cast(Integer)
            + topology_unit.c.versionOwnerId.is_not(None).cast(Integer)
            + topology_unit.c.volumeOwnerId.is_not(None).cast(Integer)
            == 1
        ),
        name="TopologyUnit_one_owner_ck",
    )
)
topology_unit.append_constraint(
    CheckConstraint(
        or_(
            and_(
                topology_unit.c.unitKind.in_(["WORK_CONTAINER", "AUDIOBOOK_WORK"]),
                topology_unit.c.workOwnerId.is_not(None),
                topology_unit.c.versionOwnerId.is_(None),
                topology_unit.c.volumeOwnerId.is_(None),
            ),
            and_(
                topology_unit.c.unitKind == "VERSION_CONTAINER",
                topology_unit.c.workOwnerId.is_(None),
                topology_unit.c.versionOwnerId.is_not(None),
                topology_unit.c.volumeOwnerId.is_(None),
            ),
            and_(
                topology_unit.c.unitKind.in_(
                    ["FLAT_VOLUME", "SINGLE_FILE_VOLUME", "MULTI_ASSET_VOLUME"]
                ),
                topology_unit.c.workOwnerId.is_(None),
                topology_unit.c.versionOwnerId.is_(None),
                topology_unit.c.volumeOwnerId.is_not(None),
            ),
        ),
        name="TopologyUnit_owner_kind_ck",
    )
)
Index(
    "TopologyUnit_work_owner_idx",
    topology_unit.c.libraryId,
    topology_unit.c.workOwnerId,
    unique=True,
    sqlite_where=topology_unit.c.workOwnerId.is_not(None),
)
Index(
    "TopologyUnit_version_owner_idx",
    topology_unit.c.libraryId,
    topology_unit.c.versionOwnerId,
    unique=True,
    sqlite_where=topology_unit.c.versionOwnerId.is_not(None),
)
Index(
    "TopologyUnit_volume_owner_idx",
    topology_unit.c.libraryId,
    topology_unit.c.volumeOwnerId,
    unique=True,
    sqlite_where=topology_unit.c.volumeOwnerId.is_not(None),
)

topology_unit_revision = _table(
    "TopologyUnitRevision",
    Column("id", _ID, primary_key=True),
    Column("libraryId", _ID, nullable=False),
    Column("unitId", _ID, nullable=False),
    Column("scanRunId", _ID, nullable=False),
    Column("unitRootEntryId", _ID, nullable=False),
    Column("revision", BigInteger, nullable=False),
    Column(
        "state",
        _enum("revisionstate", "STAGING", "ACTIVE", "SUPERSEDED", "ABANDONED"),
        nullable=False,
    ),
    Column("createdAt", _DT, nullable=False, server_default=_created()),
    ForeignKeyConstraint(
        ["libraryId", "unitId"],
        ["TopologyUnit.libraryId", "TopologyUnit.id"],
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["libraryId", "scanRunId"],
        ["LibraryScanRun.libraryId", "LibraryScanRun.id"],
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["libraryId", "unitRootEntryId"],
        ["LibrarySourceEntry.libraryId", "LibrarySourceEntry.id"],
        ondelete="CASCADE",
    ),
    UniqueConstraint("libraryId", "id", name="TopologyUnitRevision_library_id_key"),
    UniqueConstraint(
        "libraryId", "unitId", "id", name="TopologyUnitRevision_unit_id_key"
    ),
    UniqueConstraint(
        "libraryId", "unitId", "revision", name="TopologyUnitRevision_unit_revision_key"
    ),
)
topology_unit_revision.append_constraint(
    CheckConstraint(
        topology_unit_revision.c.revision > 0,
        name="TopologyUnitRevision_revision_ck",
    )
)
Index(
    "TopologyUnitRevision_one_active_idx",
    topology_unit_revision.c.libraryId,
    topology_unit_revision.c.unitId,
    unique=True,
    sqlite_where=topology_unit_revision.c.state == "ACTIVE",
)

topology_work_projection = _table(
    "TopologyWorkProjection",
    Column("id", _ID, primary_key=True),
    Column("libraryId", _ID, nullable=False),
    Column("unitRevisionId", _ID, nullable=False),
    Column("workId", _ID, nullable=False),
    Column("rootEntryId", _ID, nullable=False),
    Column("structureKey", Text, nullable=False),
    Column("sourceName", Text, nullable=False),
    Column("sortKey", Text, nullable=False),
    ForeignKeyConstraint(
        ["libraryId", "unitRevisionId"],
        ["TopologyUnitRevision.libraryId", "TopologyUnitRevision.id"],
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["libraryId", "workId"],
        ["LibraryWork.libraryId", "LibraryWork.id"],
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["libraryId", "rootEntryId"],
        ["LibrarySourceEntry.libraryId", "LibrarySourceEntry.id"],
        ondelete="CASCADE",
    ),
    UniqueConstraint(
        "libraryId", "unitRevisionId", name="TopologyWorkProjection_revision_key"
    ),
    UniqueConstraint(
        "libraryId",
        "unitRevisionId",
        "workId",
        name="TopologyWorkProjection_parent_key",
    ),
)

topology_version_projection = _table(
    "TopologyVersionProjection",
    Column("id", _ID, primary_key=True),
    Column("libraryId", _ID, nullable=False),
    Column("unitRevisionId", _ID, nullable=False),
    Column("versionId", _ID, nullable=False),
    Column("workId", _ID, nullable=False),
    Column("rootEntryId", _ID),
    Column("kind", _enum("versionkind", "IMPLICIT", "DIRECTORY"), nullable=False),
    Column("structureKey", Text, nullable=False),
    Column("sourceName", Text, nullable=False),
    Column("sortKey", Text, nullable=False),
    ForeignKeyConstraint(
        ["libraryId", "unitRevisionId"],
        ["TopologyUnitRevision.libraryId", "TopologyUnitRevision.id"],
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["libraryId", "versionId"],
        ["WorkVersion.libraryId", "WorkVersion.id"],
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["libraryId", "workId"],
        ["LibraryWork.libraryId", "LibraryWork.id"],
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["libraryId", "rootEntryId"],
        ["LibrarySourceEntry.libraryId", "LibrarySourceEntry.id"],
        ondelete="CASCADE",
    ),
    UniqueConstraint(
        "libraryId", "unitRevisionId", name="TopologyVersionProjection_revision_key"
    ),
    UniqueConstraint(
        "libraryId",
        "unitRevisionId",
        "versionId",
        name="TopologyVersionProjection_parent_key",
    ),
)

topology_volume_projection = _table(
    "TopologyVolumeProjection",
    Column("id", _ID, primary_key=True),
    Column("libraryId", _ID, nullable=False),
    Column("unitRevisionId", _ID, nullable=False),
    Column("volumeId", _ID, nullable=False),
    Column("versionId", _ID),
    Column("rootEntryId", _ID, nullable=False),
    Column(
        "sourceKind",
        _enum("sourcekind", "SINGLE_FILE", "MULTI_ASSET_AUDIO"),
        nullable=False,
    ),
    Column("structureKey", Text, nullable=False),
    Column("sourceName", Text, nullable=False),
    Column("sortKey", Text, nullable=False),
    ForeignKeyConstraint(
        ["libraryId", "unitRevisionId"],
        ["TopologyUnitRevision.libraryId", "TopologyUnitRevision.id"],
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["libraryId", "volumeId"],
        ["LibraryVolume.libraryId", "LibraryVolume.id"],
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["libraryId", "versionId"],
        ["WorkVersion.libraryId", "WorkVersion.id"],
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["libraryId", "rootEntryId"],
        ["LibrarySourceEntry.libraryId", "LibrarySourceEntry.id"],
        ondelete="CASCADE",
    ),
    UniqueConstraint(
        "libraryId", "unitRevisionId", name="TopologyVolumeProjection_revision_key"
    ),
    UniqueConstraint(
        "libraryId",
        "unitRevisionId",
        "volumeId",
        name="TopologyVolumeProjection_parent_key",
    ),
)

topology_asset_membership = _table(
    "TopologyAssetMembership",
    Column("id", _ID, primary_key=True),
    Column("libraryId", _ID, nullable=False),
    Column("unitRevisionId", _ID, nullable=False),
    Column("assetId", _ID, nullable=False),
    Column("volumeId", _ID, nullable=False),
    Column("sourceEntryId", _ID, nullable=False),
    Column(
        "role",
        _enum("assetrole", "PRIMARY", "AUDIO_TRACK", "READER_SIDECAR"),
        nullable=False,
    ),
    Column("sourceFormat", String(64), nullable=False),
    Column("discNumber", Integer),
    Column("assetOrder", Integer, nullable=False),
    Column("requiredForReading", Boolean, nullable=False, default=True),
    ForeignKeyConstraint(
        ["libraryId", "unitRevisionId"],
        ["TopologyUnitRevision.libraryId", "TopologyUnitRevision.id"],
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["libraryId", "assetId"],
        ["VolumeAsset.libraryId", "VolumeAsset.id"],
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["libraryId", "volumeId"],
        ["LibraryVolume.libraryId", "LibraryVolume.id"],
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["libraryId", "sourceEntryId"],
        ["LibrarySourceEntry.libraryId", "LibrarySourceEntry.id"],
        ondelete="CASCADE",
    ),
    UniqueConstraint(
        "libraryId",
        "unitRevisionId",
        "volumeId",
        "sourceEntryId",
        "role",
        name="TopologyAssetMembership_source_role_key",
    ),
    UniqueConstraint(
        "libraryId",
        "unitRevisionId",
        "volumeId",
        "assetOrder",
        name="TopologyAssetMembership_volume_order_key",
    ),
)
topology_asset_membership.append_constraint(
    CheckConstraint(
        topology_asset_membership.c.assetOrder >= 0,
        name="TopologyAssetMembership_order_ck",
    )
)
topology_asset_membership.append_constraint(
    CheckConstraint(
        topology_asset_membership.c.discNumber.is_(None)
        | (topology_asset_membership.c.discNumber >= 1),
        name="TopologyAssetMembership_disc_ck",
    )
)

source_write_operation = _table(
    "SourceWriteOperation",
    Column("id", _ID, primary_key=True),
    Column("libraryId", _ID, nullable=False),
    Column("actorUserId", _ID),
    Column("idempotencyKey", String(191), nullable=False),
    Column(
        "organizationMode",
        _enum("organizationmode", "FLAT", "VOLUMES", "AUDIOBOOK"),
        nullable=False,
    ),
    Column("destination", Text, nullable=False),
    Column("targetSlotKey", Text, nullable=False),
    Column(
        "state",
        _enum(
            "operationstate",
            "PREPARED",
            "FILESYSTEM_APPLIED",
            "RECONCILE_QUEUED",
            "COMPLETED",
            "CANCELLED",
            "ABANDONED_BY_LIBRARY_REMOVAL",
            "FAILED",
            "NEEDS_ATTENTION",
        ),
        nullable=False,
    ),
    Column("expectedConfigRevision", BigInteger, nullable=False),
    Column("expectedContentRevision", BigInteger),
    Column("stagingFence", BigInteger, nullable=False, default=0),
    Column("cancelRequestedAt", _DT),
    Column("ownerToken", _ID),
    Column("heartbeatAt", _DT),
    Column("temporaryStructure", JSON, nullable=False, default=dict),
    Column("finalStructure", JSON, nullable=False, default=dict),
    Column("evidence", JSON, nullable=False, default=dict),
    Column("recoveryNote", Text),
    Column("createdAt", _DT, nullable=False, server_default=_created()),
    Column("updatedAt", _DT, nullable=False, server_default=_created()),
    ForeignKeyConstraint(["libraryId"], ["CatalogLibrary.id"], ondelete="CASCADE"),
    ForeignKeyConstraint(["actorUserId"], ["User.id"], ondelete="SET NULL"),
    UniqueConstraint(
        "libraryId", "idempotencyKey", name="SourceWriteOperation_idempotency_key"
    ),
)
source_write_operation.append_constraint(
    CheckConstraint(
        source_write_operation.c.expectedConfigRevision > 0,
        name="SourceWriteOperation_config_revision_ck",
    )
)
Index(
    "SourceWriteOperation_active_slot_idx",
    source_write_operation.c.libraryId,
    source_write_operation.c.targetSlotKey,
    unique=True,
    sqlite_where=~source_write_operation.c.state.in_(
        ["COMPLETED", "CANCELLED", "ABANDONED_BY_LIBRARY_REMOVAL", "FAILED"]
    ),
)

operation_staging_lock = _table(
    "OperationStagingLock",
    Column("operationId", _ID, primary_key=True),
    Column("ownerToken", _ID, nullable=False),
    Column("fence", BigInteger, nullable=False),
    Column("heartbeatAt", _DT, nullable=False, server_default=_created()),
    Column("leaseExpiresAt", _DT, nullable=False),
    ForeignKeyConstraint(
        ["operationId"], ["SourceWriteOperation.id"], ondelete="CASCADE"
    ),
)

catalog_outbox = _table(
    "CatalogOutbox",
    Column("id", _ID, primary_key=True),
    Column("libraryId", _ID),
    Column("aggregateType", String(64), nullable=False),
    Column("aggregateId", _ID, nullable=False),
    Column("eventType", String(96), nullable=False),
    Column("eventVersion", Integer, nullable=False, default=1),
    Column("payload", JSON, nullable=False, default=dict),
    Column("availableAt", _DT, nullable=False, server_default=_created()),
    Column("deliveredAt", _DT),
    Column("attempt", Integer, nullable=False, default=0),
    Column("lastError", Text),
    Column("createdAt", _DT, nullable=False, server_default=_created()),
    ForeignKeyConstraint(["libraryId"], ["CatalogLibrary.id"], ondelete="CASCADE"),
    Index("CatalogOutbox_delivery_idx", "deliveredAt", "availableAt"),
)

administrative_audit_event = _table(
    "AdministrativeAuditEvent",
    Column("id", _ID, primary_key=True),
    Column("formerLibraryId", _ID),
    Column("operationId", _ID),
    Column("code", String(96), nullable=False),
    Column("actorKind", _enum("auditactorkind", "USER", "SYSTEM"), nullable=False),
    Column("actorUserId", _ID),
    Column("occurredAt", _DT, nullable=False, server_default=_created()),
    Column("evidence", JSON, nullable=False, default=dict),
    ForeignKeyConstraint(["actorUserId"], ["User.id"], ondelete="SET NULL"),
    ForeignKeyConstraint(
        ["operationId"], ["SourceWriteOperation.id"], ondelete="SET NULL"
    ),
    Index("AdministrativeAuditEvent_time_idx", "occurredAt"),
)


def upgrade() -> None:
    """Create every current system and catalog table through SQLAlchemy DDL."""

    bind = op.get_bind()
    metadata.create_all(bind)
    if context.is_offline_mode():
        return
    for table in metadata.tables.values():
        for index in table.indexes:
            index.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    """Reject downgrade before touching the append-only current schema."""

    raise NotImplementedError(
        "current schema lineage is append-only; downgrade is unsupported"
    )
