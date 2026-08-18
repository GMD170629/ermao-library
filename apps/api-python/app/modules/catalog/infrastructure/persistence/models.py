from __future__ import annotations

from datetime import datetime
from typing import cast

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    and_,
    func,
    or_,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.current.registry import CurrentBase
from app.modules.catalog.public import OrganizationMode, PathComparison, SourceKind

from .enums import (
    AssetRole,
    AssetValidationState,
    AttachmentRole,
    AuditActorKind,
    ContentOriginKind,
    ContentProcessorKind,
    FullRescanReason,
    GrantLevel,
    IgnoreRuleKind,
    LayoutState,
    LibraryControlState,
    LibraryHealth,
    ManifestKind,
    OperationState,
    ProcessorState,
    ReconcileIntentPhase,
    ReconcileIntentState,
    ReconcileMovedEntryType,
    RequiredDeliveryPolicy,
    RequiredManifestState,
    RevisionState,
    ScanFailureCode,
    ScanStage,
    ScanState,
    SlotState,
    SourceContentState,
    SourceEntryType,
    TopologyUnitKind,
    VersionKind,
    VolumeContentState,
    WritePolicy,
)

_ID = String(191)
_SHA256 = String(71)
_ENUM = {"native_enum": False, "create_constraint": True}


class CatalogLibrary(CurrentBase):
    __tablename__ = "CatalogLibrary"
    __table_args__ = (
        UniqueConstraint("rootPathKey", name="CatalogLibrary_rootPathKey_key"),
    )

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    root_path: Mapped[str] = mapped_column("rootPath", Text, nullable=False)
    root_path_key: Mapped[str] = mapped_column("rootPathKey", Text, nullable=False)
    organization_mode: Mapped[OrganizationMode] = mapped_column(
        "organizationMode", Enum(OrganizationMode, **_ENUM), nullable=False
    )
    topology_version: Mapped[int] = mapped_column(
        "topologyVersion", Integer, nullable=False, default=1
    )
    path_comparison: Mapped[PathComparison] = mapped_column(
        "pathComparison", Enum(PathComparison, **_ENUM), nullable=False
    )
    write_policy: Mapped[WritePolicy] = mapped_column(
        "writePolicy", Enum(WritePolicy, **_ENUM), nullable=False
    )
    control_state: Mapped[LibraryControlState] = mapped_column(
        "controlState", Enum(LibraryControlState, **_ENUM), nullable=False
    )
    observed_health: Mapped[LibraryHealth] = mapped_column(
        "observedHealth", Enum(LibraryHealth, **_ENUM), nullable=False
    )
    config_revision: Mapped[int] = mapped_column(
        "configRevision", Integer, nullable=False, default=1
    )
    topology_writer_fence: Mapped[int] = mapped_column(
        "topologyWriterFence", BigInteger, nullable=False, default=0
    )
    source_mutation_fence: Mapped[int] = mapped_column(
        "sourceMutationFence", BigInteger, nullable=False, default=0
    )
    next_scan_generation: Mapped[int] = mapped_column(
        "nextScanGeneration", BigInteger, nullable=False, default=1
    )
    last_successful_generation: Mapped[int | None] = mapped_column(
        "lastSuccessfulGeneration", BigInteger
    )
    last_successful_scan_at: Mapped[datetime | None] = mapped_column(
        "lastSuccessfulScanAt", DateTime(timezone=True)
    )
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        "updatedAt",
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        nullable=False,
    )


class LibraryWatcherState(CurrentBase):
    __tablename__ = "LibraryWatcherState"
    __table_args__ = (
        ForeignKeyConstraint(["libraryId"], ["CatalogLibrary.id"], ondelete="CASCADE"),
    )

    library_id: Mapped[str] = mapped_column("libraryId", _ID, primary_key=True)
    latest_sequence: Mapped[int] = mapped_column(
        "latestSequence", BigInteger, nullable=False, default=0
    )
    overflow_through_sequence: Mapped[int | None] = mapped_column(
        "overflowThroughSequence", BigInteger
    )
    full_rescan_reason: Mapped[FullRescanReason | None] = mapped_column(
        "fullRescanReason", Enum(FullRescanReason, **_ENUM)
    )
    updated_at: Mapped[datetime] = mapped_column(
        "updatedAt",
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        nullable=False,
    )


class LibraryReconcileIntent(CurrentBase):
    __tablename__ = "LibraryReconcileIntent"
    __table_args__ = (
        ForeignKeyConstraint(["libraryId"], ["CatalogLibrary.id"], ondelete="CASCADE"),
        UniqueConstraint(
            "libraryId",
            "throughSequence",
            name="LibraryReconcileIntent_library_through_key",
        ),
        Index(
            "LibraryReconcileIntent_claim_idx",
            "libraryId",
            "state",
            "availableAt",
            "firstSequence",
            "id",
        ),
        Index(
            "LibraryReconcileIntent_lease_idx",
            "libraryId",
            "state",
            "leaseExpiresAt",
        ),
    )

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    library_id: Mapped[str] = mapped_column("libraryId", _ID, nullable=False)
    first_sequence: Mapped[int] = mapped_column(
        "firstSequence", BigInteger, nullable=False
    )
    through_sequence: Mapped[int] = mapped_column(
        "throughSequence", BigInteger, nullable=False
    )
    scope1_path: Mapped[str] = mapped_column("scope1Path", Text, nullable=False)
    scope1_key: Mapped[str] = mapped_column("scope1Key", Text, nullable=False)
    scope2_path: Mapped[str | None] = mapped_column("scope2Path", Text)
    scope2_key: Mapped[str | None] = mapped_column("scope2Key", Text)
    coalesce_key: Mapped[str] = mapped_column(
        "coalesceKey", String(191), nullable=False
    )
    move_old_path: Mapped[list[str] | None] = mapped_column(
        "moveOldPath", JSON(none_as_null=True)
    )
    move_new_path: Mapped[list[str] | None] = mapped_column(
        "moveNewPath", JSON(none_as_null=True)
    )
    moved_entry_type: Mapped[ReconcileMovedEntryType | None] = mapped_column(
        "movedEntryType", Enum(ReconcileMovedEntryType, **_ENUM)
    )
    state: Mapped[ReconcileIntentState] = mapped_column(
        Enum(ReconcileIntentState, **_ENUM), nullable=False
    )
    phase: Mapped[ReconcileIntentPhase] = mapped_column(
        Enum(ReconcileIntentPhase, **_ENUM), nullable=False
    )
    lease_owner: Mapped[str | None] = mapped_column("leaseOwner", _ID)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        "leaseExpiresAt", DateTime(timezone=True)
    )
    topology_writer_fence: Mapped[int | None] = mapped_column(
        "topologyWriterFence", BigInteger
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime] = mapped_column(
        "availableAt", DateTime(timezone=True), nullable=False
    )
    fold_after_source_entry_id: Mapped[str | None] = mapped_column(
        "foldAfterSourceEntryId", _ID
    )
    config_revision: Mapped[int] = mapped_column(
        "configRevision", BigInteger, nullable=False
    )
    organization_mode: Mapped[OrganizationMode] = mapped_column(
        "organizationMode", Enum(OrganizationMode, **_ENUM), nullable=False
    )
    topology_version: Mapped[int] = mapped_column(
        "topologyVersion", Integer, nullable=False
    )
    path_comparison: Mapped[PathComparison] = mapped_column(
        "pathComparison", Enum(PathComparison, **_ENUM), nullable=False
    )
    root_path_snapshot: Mapped[str] = mapped_column(
        "rootPathSnapshot", Text, nullable=False
    )
    root_identity_snapshot: Mapped[str] = mapped_column(
        "rootIdentitySnapshot", String(191), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        "createdAt", DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        "updatedAt", DateTime(timezone=True), nullable=False
    )


class LibraryIgnoreRule(CurrentBase):
    __tablename__ = "LibraryIgnoreRule"
    __table_args__ = (
        ForeignKeyConstraint(["libraryId"], ["CatalogLibrary.id"], ondelete="CASCADE"),
        UniqueConstraint(
            "libraryId", "ruleKey", name="LibraryIgnoreRule_library_rule_key"
        ),
        Index("LibraryIgnoreRule_library_enabled_idx", "libraryId", "enabled"),
    )

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    library_id: Mapped[str] = mapped_column("libraryId", _ID, nullable=False)
    rule_key: Mapped[str] = mapped_column("ruleKey", Text, nullable=False)
    pattern: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[IgnoreRuleKind] = mapped_column(
        Enum(IgnoreRuleKind, **_ENUM), nullable=False
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    config_revision: Mapped[int] = mapped_column(
        "configRevision", BigInteger, nullable=False, default=1
    )
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        "updatedAt",
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        nullable=False,
    )


class UserLibraryGrant(CurrentBase):
    __tablename__ = "UserLibraryGrant"
    __table_args__ = (
        ForeignKeyConstraint(["userId"], ["User.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["libraryId"], ["CatalogLibrary.id"], ondelete="CASCADE"),
        UniqueConstraint(
            "userId", "libraryId", name="UserLibraryGrant_user_library_key"
        ),
        Index("UserLibraryGrant_library_level_idx", "libraryId", "level"),
    )

    user_id: Mapped[str] = mapped_column("userId", _ID, primary_key=True)
    library_id: Mapped[str] = mapped_column("libraryId", _ID, primary_key=True)
    level: Mapped[GrantLevel] = mapped_column(Enum(GrantLevel, **_ENUM), nullable=False)
    scope_epoch: Mapped[int] = mapped_column(
        "scopeEpoch", BigInteger, nullable=False, default=1
    )
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        "updatedAt",
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        nullable=False,
    )


class LibraryRootRegistryLock(CurrentBase):
    __tablename__ = "LibraryRootRegistryLock"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    owner_token: Mapped[str | None] = mapped_column("ownerToken", _ID)
    fence: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        "leaseExpiresAt", DateTime(timezone=True)
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(
        "heartbeatAt", DateTime(timezone=True)
    )
    updated_at: Mapped[datetime] = mapped_column(
        "updatedAt",
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        nullable=False,
    )


class LibraryWork(CurrentBase):
    __tablename__ = "LibraryWork"
    __table_args__ = (
        ForeignKeyConstraint(["libraryId"], ["CatalogLibrary.id"], ondelete="CASCADE"),
        UniqueConstraint("libraryId", "id", name="LibraryWork_library_id_key"),
    )

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    library_id: Mapped[str] = mapped_column("libraryId", _ID, nullable=False)
    metadata_revision: Mapped[int] = mapped_column(
        "metadataRevision", BigInteger, nullable=False, default=0
    )
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        "updatedAt",
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        nullable=False,
    )


class WorkVersion(CurrentBase):
    __tablename__ = "WorkVersion"
    __table_args__ = (
        ForeignKeyConstraint(["libraryId"], ["CatalogLibrary.id"], ondelete="CASCADE"),
        UniqueConstraint("libraryId", "id", name="WorkVersion_library_id_key"),
    )

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    library_id: Mapped[str] = mapped_column("libraryId", _ID, nullable=False)
    metadata_revision: Mapped[int] = mapped_column(
        "metadataRevision", BigInteger, nullable=False, default=0
    )
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        "updatedAt",
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        nullable=False,
    )


class LibraryVolume(CurrentBase):
    __tablename__ = "LibraryVolume"
    __table_args__ = (
        ForeignKeyConstraint(["libraryId"], ["CatalogLibrary.id"], ondelete="CASCADE"),
        UniqueConstraint("libraryId", "id", name="LibraryVolume_library_id_key"),
    )

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    library_id: Mapped[str] = mapped_column("libraryId", _ID, nullable=False)
    reading_morphology: Mapped[str] = mapped_column(
        "readingMorphology", String(32), nullable=False
    )
    content_state: Mapped[VolumeContentState] = mapped_column(
        "contentState", Enum(VolumeContentState, **_ENUM), nullable=False
    )
    content_revision: Mapped[int] = mapped_column(
        "contentRevision", BigInteger, nullable=False, default=0
    )
    required_manifest_revision: Mapped[int] = mapped_column(
        "requiredManifestRevision", BigInteger, nullable=False, default=0
    )
    optional_manifest_revision: Mapped[int] = mapped_column(
        "optionalManifestRevision", BigInteger, nullable=False, default=0
    )
    metadata_revision: Mapped[int] = mapped_column(
        "metadataRevision", BigInteger, nullable=False, default=0
    )
    required_manifest_digest: Mapped[str | None] = mapped_column(
        "requiredManifestDigest", String(191)
    )
    publication_fingerprint: Mapped[str | None] = mapped_column(
        "publicationFingerprint", String(191)
    )
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        "updatedAt",
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        nullable=False,
    )


class VolumeAsset(CurrentBase):
    __tablename__ = "VolumeAsset"
    __table_args__ = (
        ForeignKeyConstraint(["libraryId"], ["CatalogLibrary.id"], ondelete="CASCADE"),
        UniqueConstraint("libraryId", "id", name="VolumeAsset_library_id_key"),
    )

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    library_id: Mapped[str] = mapped_column("libraryId", _ID, nullable=False)
    source_format: Mapped[str] = mapped_column(
        "sourceFormat", String(64), nullable=False
    )
    mime_type: Mapped[str | None] = mapped_column("mimeType", String(191))
    size_bytes: Mapped[int | None] = mapped_column("sizeBytes", BigInteger)
    content_digest: Mapped[str | None] = mapped_column("contentDigest", String(191))
    embedded_track_number: Mapped[int | None] = mapped_column(
        "embeddedTrackNumber", Integer
    )
    validation_state: Mapped[AssetValidationState] = mapped_column(
        "validationState", Enum(AssetValidationState, **_ENUM), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        "updatedAt",
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        nullable=False,
    )


class LibrarySourceEntry(CurrentBase):
    __tablename__ = "LibrarySourceEntry"
    __table_args__ = (
        ForeignKeyConstraint(["libraryId"], ["CatalogLibrary.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["libraryId", "parentEntryId"],
            ["LibrarySourceEntry.libraryId", "LibrarySourceEntry.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("libraryId", "id", name="LibrarySourceEntry_library_id_key"),
    )

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    library_id: Mapped[str] = mapped_column("libraryId", _ID, nullable=False)
    parent_entry_id: Mapped[str | None] = mapped_column("parentEntryId", _ID)
    local_name: Mapped[str] = mapped_column("localName", Text, nullable=False)
    local_name_key: Mapped[str] = mapped_column("localNameKey", Text, nullable=False)
    entry_type: Mapped[SourceEntryType] = mapped_column(
        "entryType", Enum(SourceEntryType, **_ENUM), nullable=False
    )
    filesystem_identity: Mapped[str | None] = mapped_column(
        "filesystemIdentity", String(191)
    )
    size_bytes: Mapped[int | None] = mapped_column("sizeBytes", BigInteger)
    modified_ns: Mapped[int | None] = mapped_column("modifiedNs", BigInteger)
    last_seen_generation: Mapped[int | None] = mapped_column(
        "lastSeenGeneration", BigInteger
    )
    absence_confirmed_at: Mapped[datetime | None] = mapped_column(
        "absenceConfirmedAt", DateTime(timezone=True)
    )
    children_presence_epoch: Mapped[int] = mapped_column(
        "childrenPresenceEpoch", BigInteger, nullable=False, default=0
    )
    next_children_presence_epoch: Mapped[int] = mapped_column(
        "nextChildrenPresenceEpoch", BigInteger, nullable=False, default=0
    )
    observed_parent_presence_epoch: Mapped[int | None] = mapped_column(
        "observedParentPresenceEpoch", BigInteger
    )
    pending_observed_parent_presence_epoch: Mapped[int | None] = mapped_column(
        "pendingObservedParentPresenceEpoch", BigInteger
    )
    layout_state: Mapped[LayoutState] = mapped_column(
        "layoutState", Enum(LayoutState, **_ENUM), nullable=False
    )
    slot_state: Mapped[SlotState] = mapped_column(
        "slotState", Enum(SlotState, **_ENUM), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        "updatedAt",
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        nullable=False,
    )


class SourceAttachment(CurrentBase):
    __tablename__ = "SourceAttachment"
    __table_args__ = (
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
        UniqueConstraint(
            "libraryId", "sourceEntryId", name="SourceAttachment_entry_key"
        ),
    )

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    library_id: Mapped[str] = mapped_column("libraryId", _ID, nullable=False)
    source_entry_id: Mapped[str] = mapped_column("sourceEntryId", _ID, nullable=False)
    work_id: Mapped[str | None] = mapped_column("workId", _ID)
    version_id: Mapped[str | None] = mapped_column("versionId", _ID)
    volume_id: Mapped[str | None] = mapped_column("volumeId", _ID)
    role: Mapped[AttachmentRole] = mapped_column(
        Enum(AttachmentRole, **_ENUM), nullable=False
    )
    source_format: Mapped[str | None] = mapped_column("sourceFormat", String(64))
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        nullable=False,
    )


class LibraryScanRun(CurrentBase):
    __tablename__ = "LibraryScanRun"
    __table_args__ = (
        ForeignKeyConstraint(["libraryId"], ["CatalogLibrary.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["createdByUserId"], ["User.id"], ondelete="SET NULL"),
        UniqueConstraint("libraryId", "id", name="LibraryScanRun_library_id_key"),
        UniqueConstraint(
            "libraryId", "generation", name="LibraryScanRun_library_generation_key"
        ),
        Index("LibraryScanRun_library_state_idx", "libraryId", "state"),
    )

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    library_id: Mapped[str] = mapped_column("libraryId", _ID, nullable=False)
    generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    config_revision: Mapped[int] = mapped_column(
        "configRevision", BigInteger, nullable=False
    )
    mode_snapshot: Mapped[OrganizationMode] = mapped_column(
        "modeSnapshot", Enum(OrganizationMode, **_ENUM), nullable=False
    )
    root_path_snapshot: Mapped[str] = mapped_column(
        "rootPathSnapshot", Text, nullable=False
    )
    path_comparison_snapshot: Mapped[PathComparison] = mapped_column(
        "pathComparisonSnapshot", Enum(PathComparison, **_ENUM), nullable=False
    )
    topology_version_snapshot: Mapped[int] = mapped_column(
        "topologyVersionSnapshot", Integer, nullable=False
    )
    root_identity_snapshot: Mapped[str | None] = mapped_column(
        "rootIdentitySnapshot", String(191)
    )
    topology_writer_fence: Mapped[int] = mapped_column(
        "topologyWriterFence", BigInteger, nullable=False
    )
    watcher_sequence_watermark: Mapped[int] = mapped_column(
        "watcherSequenceWatermark", BigInteger, nullable=False
    )
    state: Mapped[ScanState] = mapped_column(Enum(ScanState, **_ENUM), nullable=False)
    failure_code: Mapped[ScanFailureCode | None] = mapped_column(
        "failureCode", Enum(ScanFailureCode, **_ENUM)
    )
    lease_owner: Mapped[str | None] = mapped_column("leaseOwner", _ID)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        "leaseExpiresAt", DateTime(timezone=True)
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(
        "heartbeatAt", DateTime(timezone=True)
    )
    stage: Mapped[ScanStage] = mapped_column(Enum(ScanStage, **_ENUM), nullable=False)
    discovered_count: Mapped[int] = mapped_column(
        "discoveredCount", BigInteger, nullable=False, default=0
    )
    diagnostic_count: Mapped[int] = mapped_column(
        "diagnosticCount", BigInteger, nullable=False, default=0
    )
    started_at: Mapped[datetime | None] = mapped_column(
        "startedAt", DateTime(timezone=True)
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        "finishedAt", DateTime(timezone=True)
    )
    created_by_user_id: Mapped[str | None] = mapped_column("createdByUserId", _ID)
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        nullable=False,
    )


cast(Table, LibraryScanRun.__table__).append_constraint(
    CheckConstraint(
        or_(
            and_(
                LibraryScanRun.state == ScanState.FAILED,
                LibraryScanRun.failure_code.is_not(None),
            ),
            and_(
                LibraryScanRun.state != ScanState.FAILED,
                LibraryScanRun.failure_code.is_(None),
            ),
        ),
        name="LibraryScanRun_failure_shape_ck",
    )
)
cast(Table, LibraryScanRun.__table__).append_constraint(
    CheckConstraint(
        and_(
            LibraryScanRun.generation > 0,
            LibraryScanRun.config_revision > 0,
            LibraryScanRun.topology_version_snapshot > 0,
            LibraryScanRun.topology_writer_fence > 0,
            LibraryScanRun.discovered_count >= 0,
            LibraryScanRun.diagnostic_count >= 0,
        ),
        name="LibraryScanRun_positive_ck",
    )
)
cast(Table, LibraryScanRun.__table__).append_constraint(
    CheckConstraint(
        or_(
            and_(
                LibraryScanRun.state == ScanState.PENDING,
                LibraryScanRun.stage == ScanStage.DISCOVER,
                LibraryScanRun.lease_owner.is_not(None),
                LibraryScanRun.lease_expires_at.is_not(None),
                LibraryScanRun.root_identity_snapshot.is_(None),
                LibraryScanRun.started_at.is_(None),
                LibraryScanRun.finished_at.is_(None),
            ),
            and_(
                LibraryScanRun.state == ScanState.RUNNING,
                LibraryScanRun.stage.in_([ScanStage.DISCOVER, ScanStage.RECONCILE]),
                LibraryScanRun.lease_owner.is_not(None),
                LibraryScanRun.lease_expires_at.is_not(None),
                LibraryScanRun.root_identity_snapshot.is_not(None),
                LibraryScanRun.started_at.is_not(None),
                LibraryScanRun.finished_at.is_(None),
            ),
            and_(
                LibraryScanRun.state == ScanState.FINALIZING,
                LibraryScanRun.stage == ScanStage.FINALIZE,
                LibraryScanRun.lease_owner.is_not(None),
                LibraryScanRun.lease_expires_at.is_not(None),
                LibraryScanRun.root_identity_snapshot.is_not(None),
                LibraryScanRun.started_at.is_not(None),
                LibraryScanRun.finished_at.is_(None),
            ),
            and_(
                LibraryScanRun.state == ScanState.COMPLETED,
                LibraryScanRun.stage == ScanStage.FINALIZE,
                LibraryScanRun.lease_owner.is_(None),
                LibraryScanRun.lease_expires_at.is_(None),
                LibraryScanRun.root_identity_snapshot.is_not(None),
                LibraryScanRun.started_at.is_not(None),
                LibraryScanRun.finished_at.is_not(None),
            ),
            and_(
                LibraryScanRun.state.in_([ScanState.FAILED, ScanState.CANCELLED]),
                LibraryScanRun.lease_owner.is_(None),
                LibraryScanRun.lease_expires_at.is_(None),
                LibraryScanRun.finished_at.is_not(None),
                or_(
                    and_(
                        LibraryScanRun.root_identity_snapshot.is_(None),
                        LibraryScanRun.started_at.is_(None),
                    ),
                    and_(
                        LibraryScanRun.root_identity_snapshot.is_not(None),
                        LibraryScanRun.started_at.is_not(None),
                    ),
                ),
            ),
        ),
        name="LibraryScanRun_state_shape_ck",
    )
)


class LibraryScanWorkItem(CurrentBase):
    __tablename__ = "LibraryScanWorkItem"
    __table_args__ = (
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
        Index(
            "LibraryScanWorkItem_lease_recovery_idx",
            "libraryId",
            "state",
            "leaseExpiresAt",
        ),
    )

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    library_id: Mapped[str] = mapped_column("libraryId", _ID, nullable=False)
    scan_run_id: Mapped[str] = mapped_column("scanRunId", _ID, nullable=False)
    root_path_snapshot: Mapped[str] = mapped_column(
        "rootPathSnapshot", Text, nullable=False
    )
    subtree_root_entry_id: Mapped[str | None] = mapped_column("subtreeRootEntryId", _ID)
    scope_relative_path: Mapped[str] = mapped_column(
        "scopeRelativePath", Text, nullable=False
    )
    state: Mapped[ScanState] = mapped_column(Enum(ScanState, **_ENUM), nullable=False)
    stage: Mapped[ScanStage] = mapped_column(Enum(ScanStage, **_ENUM), nullable=False)
    lease_owner: Mapped[str | None] = mapped_column("leaseOwner", _ID)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        "leaseExpiresAt", DateTime(timezone=True)
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime] = mapped_column(
        "availableAt",
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        nullable=False,
    )
    idempotency_key: Mapped[str] = mapped_column(
        "idempotencyKey", String(191), nullable=False
    )
    discovered_count: Mapped[int] = mapped_column(
        "discoveredCount", BigInteger, nullable=False, default=0
    )
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        nullable=False,
    )


cast(Table, LibraryScanWorkItem.__table__).append_constraint(
    CheckConstraint(
        and_(
            LibraryScanWorkItem.subtree_root_entry_id.is_(None),
            LibraryScanWorkItem.scope_relative_path == "",
            LibraryScanWorkItem.attempt >= 0,
            LibraryScanWorkItem.discovered_count >= 0,
            or_(
                and_(
                    LibraryScanWorkItem.state == ScanState.PENDING,
                    LibraryScanWorkItem.lease_owner.is_(None),
                    LibraryScanWorkItem.lease_expires_at.is_(None),
                ),
                and_(
                    LibraryScanWorkItem.state == ScanState.RUNNING,
                    LibraryScanWorkItem.lease_owner.is_not(None),
                    LibraryScanWorkItem.lease_expires_at.is_not(None),
                ),
            ),
        ),
        name="LibraryScanWorkItem_root_shape_ck",
    )
)


class PathCollisionObservation(CurrentBase):
    __tablename__ = "PathCollisionObservation"
    __table_args__ = (
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

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    library_id: Mapped[str] = mapped_column("libraryId", _ID, nullable=False)
    scan_run_id: Mapped[str] = mapped_column("scanRunId", _ID, nullable=False)
    parent_entry_id: Mapped[str] = mapped_column("parentEntryId", _ID, nullable=False)
    local_name: Mapped[str] = mapped_column("localName", Text, nullable=False)
    local_name_key: Mapped[str] = mapped_column("localNameKey", Text, nullable=False)
    evidence: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    observed_at: Mapped[datetime] = mapped_column(
        "observedAt",
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        nullable=False,
    )


class LayoutDiagnostic(CurrentBase):
    __tablename__ = "LayoutDiagnostic"
    __table_args__ = (
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

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    library_id: Mapped[str] = mapped_column("libraryId", _ID, nullable=False)
    scan_run_id: Mapped[str | None] = mapped_column("scanRunId", _ID)
    reconcile_origin_id: Mapped[str | None] = mapped_column("reconcileOriginId", _ID)
    generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    config_revision: Mapped[int] = mapped_column(
        "configRevision", BigInteger, nullable=False
    )
    scope_relative_path: Mapped[str] = mapped_column(
        "scopeRelativePath", Text, nullable=False
    )
    code: Mapped[str] = mapped_column(String(96), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    parameters: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    first_observed_at: Mapped[datetime] = mapped_column(
        "firstObservedAt",
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        nullable=False,
    )
    last_observed_at: Mapped[datetime] = mapped_column(
        "lastObservedAt",
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        nullable=False,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        "resolvedAt", DateTime(timezone=True)
    )


class TopologyUnit(CurrentBase):
    __tablename__ = "TopologyUnit"
    __table_args__ = (
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

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    library_id: Mapped[str] = mapped_column("libraryId", _ID, nullable=False)
    unit_kind: Mapped[TopologyUnitKind] = mapped_column(
        "unitKind", Enum(TopologyUnitKind, **_ENUM), nullable=False
    )
    work_owner_id: Mapped[str | None] = mapped_column("workOwnerId", _ID)
    version_owner_id: Mapped[str | None] = mapped_column("versionOwnerId", _ID)
    volume_owner_id: Mapped[str | None] = mapped_column("volumeOwnerId", _ID)
    active_revision_id: Mapped[str | None] = mapped_column("activeRevisionId", _ID)
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        nullable=False,
    )


class TopologyUnitRevision(CurrentBase):
    __tablename__ = "TopologyUnitRevision"
    __table_args__ = (
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
            "libraryId",
            "unitId",
            "revision",
            name="TopologyUnitRevision_unit_revision_key",
        ),
    )

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    library_id: Mapped[str] = mapped_column("libraryId", _ID, nullable=False)
    unit_id: Mapped[str] = mapped_column("unitId", _ID, nullable=False)
    scan_run_id: Mapped[str | None] = mapped_column("scanRunId", _ID)
    reconcile_origin_id: Mapped[str | None] = mapped_column("reconcileOriginId", _ID)
    unit_root_entry_id: Mapped[str] = mapped_column(
        "unitRootEntryId", _ID, nullable=False
    )
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    state: Mapped[RevisionState] = mapped_column(
        Enum(RevisionState, **_ENUM), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        nullable=False,
    )


class TopologyWorkProjection(CurrentBase):
    __tablename__ = "TopologyWorkProjection"
    __table_args__ = (
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

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    library_id: Mapped[str] = mapped_column("libraryId", _ID, nullable=False)
    unit_revision_id: Mapped[str] = mapped_column("unitRevisionId", _ID, nullable=False)
    work_id: Mapped[str] = mapped_column("workId", _ID, nullable=False)
    root_entry_id: Mapped[str] = mapped_column("rootEntryId", _ID, nullable=False)
    structure_key: Mapped[str] = mapped_column("structureKey", Text, nullable=False)
    source_name: Mapped[str] = mapped_column("sourceName", Text, nullable=False)
    sort_key: Mapped[str] = mapped_column("sortKey", Text, nullable=False)


class TopologyVersionProjection(CurrentBase):
    __tablename__ = "TopologyVersionProjection"
    __table_args__ = (
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

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    library_id: Mapped[str] = mapped_column("libraryId", _ID, nullable=False)
    unit_revision_id: Mapped[str] = mapped_column("unitRevisionId", _ID, nullable=False)
    version_id: Mapped[str] = mapped_column("versionId", _ID, nullable=False)
    work_id: Mapped[str] = mapped_column("workId", _ID, nullable=False)
    root_entry_id: Mapped[str | None] = mapped_column("rootEntryId", _ID)
    kind: Mapped[VersionKind] = mapped_column(
        Enum(VersionKind, **_ENUM), nullable=False
    )
    structure_key: Mapped[str] = mapped_column("structureKey", Text, nullable=False)
    source_name: Mapped[str | None] = mapped_column("sourceName", Text)
    sort_key: Mapped[str] = mapped_column("sortKey", Text, nullable=False)


class TopologyVolumeProjection(CurrentBase):
    __tablename__ = "TopologyVolumeProjection"
    __table_args__ = (
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
            "libraryId",
            "unitRevisionId",
            "volumeId",
            name="TopologyVolumeProjection_parent_key",
        ),
    )

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    library_id: Mapped[str] = mapped_column("libraryId", _ID, nullable=False)
    unit_revision_id: Mapped[str] = mapped_column("unitRevisionId", _ID, nullable=False)
    volume_id: Mapped[str] = mapped_column("volumeId", _ID, nullable=False)
    version_id: Mapped[str] = mapped_column("versionId", _ID, nullable=False)
    root_entry_id: Mapped[str] = mapped_column("rootEntryId", _ID, nullable=False)
    source_kind: Mapped[SourceKind] = mapped_column(
        "sourceKind", Enum(SourceKind, **_ENUM), nullable=False
    )
    reading_morphology: Mapped[str] = mapped_column(
        "readingMorphology", String(32), nullable=False
    )
    structure_key: Mapped[str] = mapped_column("structureKey", Text, nullable=False)
    source_name: Mapped[str] = mapped_column("sourceName", Text, nullable=False)
    sort_key: Mapped[str] = mapped_column("sortKey", Text, nullable=False)


class TopologyAssetMembership(CurrentBase):
    __tablename__ = "TopologyAssetMembership"
    __table_args__ = (
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

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    library_id: Mapped[str] = mapped_column("libraryId", _ID, nullable=False)
    unit_revision_id: Mapped[str] = mapped_column("unitRevisionId", _ID, nullable=False)
    asset_id: Mapped[str] = mapped_column("assetId", _ID, nullable=False)
    volume_id: Mapped[str] = mapped_column("volumeId", _ID, nullable=False)
    source_entry_id: Mapped[str] = mapped_column("sourceEntryId", _ID, nullable=False)
    role: Mapped[AssetRole] = mapped_column(Enum(AssetRole, **_ENUM), nullable=False)
    source_format: Mapped[str] = mapped_column(
        "sourceFormat", String(64), nullable=False
    )
    disc_number: Mapped[int | None] = mapped_column("discNumber", Integer)
    asset_order: Mapped[int] = mapped_column("assetOrder", Integer, nullable=False)
    required_for_reading: Mapped[bool] = mapped_column(
        "requiredForReading", Boolean, nullable=False, default=True
    )


class ContentTopologyProjectionState(CurrentBase):
    """One durable per-library cursor for bounded active-topology projection."""

    __tablename__ = "ContentTopologyProjectionState"
    __table_args__ = (
        ForeignKeyConstraint(
            ["libraryId"],
            ["CatalogLibrary.id"],
            ondelete="CASCADE",
        ),
        Index(
            "ContentTopologyProjectionState_pending_idx",
            "requestedEpoch",
            "appliedEpoch",
            "libraryId",
        ),
    )

    library_id: Mapped[str] = mapped_column("libraryId", _ID, primary_key=True)
    requested_epoch: Mapped[int] = mapped_column(
        "requestedEpoch", BigInteger, nullable=False, default=0
    )
    claimed_epoch: Mapped[int] = mapped_column(
        "claimedEpoch", BigInteger, nullable=False, default=0
    )
    applied_epoch: Mapped[int] = mapped_column(
        "appliedEpoch", BigInteger, nullable=False, default=0
    )
    cursor_volume_id: Mapped[str | None] = mapped_column("cursorVolumeId", _ID)
    updated_at: Mapped[datetime] = mapped_column(
        "updatedAt",
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        nullable=False,
    )


class SourceContentFact(CurrentBase):
    """Current bounded inspection fact for one admitted source file."""

    __tablename__ = "SourceContentFact"
    __table_args__ = (
        ForeignKeyConstraint(
            ["libraryId", "sourceEntryId"],
            ["LibrarySourceEntry.libraryId", "LibrarySourceEntry.id"],
            ondelete="CASCADE",
        ),
    )

    library_id: Mapped[str] = mapped_column("libraryId", _ID, primary_key=True)
    source_entry_id: Mapped[str] = mapped_column("sourceEntryId", _ID, primary_key=True)
    input_revision: Mapped[int] = mapped_column(
        "inputRevision", BigInteger, nullable=False
    )
    work_revision: Mapped[int] = mapped_column(
        "workRevision", BigInteger, nullable=False
    )
    digest_input_revision: Mapped[int | None] = mapped_column(
        "digestInputRevision", BigInteger
    )
    admission: Mapped[str] = mapped_column(String(16), nullable=False)
    source_format: Mapped[str | None] = mapped_column("sourceFormat", String(64))
    filesystem_identity: Mapped[str] = mapped_column(
        "filesystemIdentity", String(191), nullable=False
    )
    device_id: Mapped[int] = mapped_column("deviceId", BigInteger, nullable=False)
    file_id: Mapped[int] = mapped_column("fileId", BigInteger, nullable=False)
    size_bytes: Mapped[int] = mapped_column("sizeBytes", BigInteger, nullable=False)
    modified_ns: Mapped[int] = mapped_column("modifiedNs", BigInteger, nullable=False)
    policy_version: Mapped[int] = mapped_column(
        "policyVersion", Integer, nullable=False
    )
    origin_kind: Mapped[ContentOriginKind] = mapped_column(
        "originKind", Enum(ContentOriginKind, **_ENUM), nullable=False
    )
    origin_id: Mapped[str | None] = mapped_column("originId", _ID)
    origin_sequence: Mapped[int] = mapped_column(
        "originSequence", BigInteger, nullable=False
    )
    available_at: Mapped[datetime] = mapped_column(
        "availableAt", DateTime(timezone=True), nullable=False
    )
    state: Mapped[SourceContentState] = mapped_column(
        Enum(SourceContentState, **_ENUM), nullable=False
    )
    content_digest: Mapped[str | None] = mapped_column("contentDigest", _SHA256)
    lease_owner: Mapped[str | None] = mapped_column("leaseOwner", _ID)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        "leaseExpiresAt", DateTime(timezone=True)
    )
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        "updatedAt",
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        nullable=False,
    )


class VolumeManifestHeader(CurrentBase):
    """Immutable manifest header; only ACTIVE rows are Reader-visible."""

    __tablename__ = "VolumeManifestHeader"
    __table_args__ = (
        ForeignKeyConstraint(
            ["libraryId", "volumeId"],
            ["LibraryVolume.libraryId", "LibraryVolume.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["libraryId", "topologyUnitRevisionId"],
            ["TopologyUnitRevision.libraryId", "TopologyUnitRevision.id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("libraryId", "id", name="VolumeManifestHeader_library_id_key"),
        UniqueConstraint(
            "libraryId",
            "volumeId",
            "id",
            name="VolumeManifestHeader_volume_id_key",
        ),
        UniqueConstraint(
            "libraryId",
            "volumeId",
            "kind",
            "processorVersion",
            "processingRevision",
            name="VolumeManifestHeader_build_key",
        ),
    )

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    library_id: Mapped[str] = mapped_column("libraryId", _ID, nullable=False)
    volume_id: Mapped[str] = mapped_column("volumeId", _ID, nullable=False)
    kind: Mapped[ManifestKind] = mapped_column(
        Enum(ManifestKind, **_ENUM), nullable=False
    )
    state: Mapped[RequiredManifestState] = mapped_column(
        Enum(RequiredManifestState, **_ENUM), nullable=False
    )
    topology_unit_revision_id: Mapped[str] = mapped_column(
        "topologyUnitRevisionId", _ID, nullable=False
    )
    processor_version: Mapped[str] = mapped_column(
        "processorVersion", String(64), nullable=False
    )
    processing_revision: Mapped[int] = mapped_column(
        "processingRevision", BigInteger, nullable=False
    )
    topology_version: Mapped[int] = mapped_column(
        "topologyVersion", Integer, nullable=False
    )
    reading_morphology: Mapped[str] = mapped_column(
        "readingMorphology", String(32), nullable=False
    )
    delivery_policy: Mapped[RequiredDeliveryPolicy] = mapped_column(
        "deliveryPolicy", Enum(RequiredDeliveryPolicy, **_ENUM), nullable=False
    )
    delivery_policy_version: Mapped[int] = mapped_column(
        "deliveryPolicyVersion", Integer, nullable=False
    )
    base_content_revision: Mapped[int] = mapped_column(
        "baseContentRevision", BigInteger, nullable=False
    )
    base_required_manifest_revision: Mapped[int] = mapped_column(
        "baseRequiredManifestRevision", BigInteger, nullable=False
    )
    published_content_revision: Mapped[int | None] = mapped_column(
        "publishedContentRevision", BigInteger
    )
    published_required_manifest_revision: Mapped[int | None] = mapped_column(
        "publishedRequiredManifestRevision", BigInteger
    )
    expected_entry_count: Mapped[int] = mapped_column(
        "expectedEntryCount", Integer, nullable=False
    )
    staged_entry_count: Mapped[int] = mapped_column(
        "stagedEntryCount", Integer, nullable=False
    )
    source_bytes_digest: Mapped[str] = mapped_column(
        "sourceBytesDigest", _SHA256, nullable=False
    )
    content_facts_digest: Mapped[str] = mapped_column(
        "contentFactsDigest", _SHA256, nullable=False
    )
    delivery_facts_digest: Mapped[str] = mapped_column(
        "deliveryFactsDigest", _SHA256, nullable=False
    )
    activated_at: Mapped[datetime | None] = mapped_column(
        "activatedAt", DateTime(timezone=True)
    )
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        nullable=False,
    )


class VolumeManifestEntry(CurrentBase):
    """One canonical, ordered required asset snapshot in a manifest."""

    __tablename__ = "VolumeManifestEntry"
    __table_args__ = (
        ForeignKeyConstraint(
            ["libraryId", "volumeId", "manifestId"],
            [
                "VolumeManifestHeader.libraryId",
                "VolumeManifestHeader.volumeId",
                "VolumeManifestHeader.id",
            ],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["libraryId", "assetId"],
            ["VolumeAsset.libraryId", "VolumeAsset.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["libraryId", "sourceEntryId"],
            ["LibrarySourceEntry.libraryId", "LibrarySourceEntry.id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "libraryId",
            "manifestId",
            "assetOrder",
            name="VolumeManifestEntry_order_key",
        ),
        UniqueConstraint(
            "libraryId",
            "manifestId",
            "assetId",
            name="VolumeManifestEntry_asset_key",
        ),
    )

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    library_id: Mapped[str] = mapped_column("libraryId", _ID, nullable=False)
    volume_id: Mapped[str] = mapped_column("volumeId", _ID, nullable=False)
    manifest_id: Mapped[str] = mapped_column("manifestId", _ID, nullable=False)
    asset_id: Mapped[str] = mapped_column("assetId", _ID, nullable=False)
    source_entry_id: Mapped[str] = mapped_column("sourceEntryId", _ID, nullable=False)
    source_fact_revision: Mapped[int] = mapped_column(
        "sourceFactRevision", BigInteger, nullable=False
    )
    role: Mapped[AssetRole] = mapped_column(Enum(AssetRole, **_ENUM), nullable=False)
    source_format: Mapped[str] = mapped_column(
        "sourceFormat", String(64), nullable=False
    )
    mime_type: Mapped[str] = mapped_column("mimeType", String(191), nullable=False)
    size_bytes: Mapped[int] = mapped_column("sizeBytes", BigInteger, nullable=False)
    content_digest: Mapped[str] = mapped_column(
        "contentDigest", _SHA256, nullable=False
    )
    filesystem_identity: Mapped[str] = mapped_column(
        "filesystemIdentity", String(191), nullable=False
    )
    modified_ns: Mapped[int] = mapped_column("modifiedNs", BigInteger, nullable=False)
    asset_order: Mapped[int] = mapped_column("assetOrder", Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        nullable=False,
    )


class VolumeProcessingFact(CurrentBase):
    """Current leased processing intent for one Volume capability."""

    __tablename__ = "VolumeProcessingFact"
    __table_args__ = (
        ForeignKeyConstraint(
            ["libraryId", "volumeId"],
            ["LibraryVolume.libraryId", "LibraryVolume.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["libraryId", "activeTopologyRevisionId"],
            ["TopologyUnitRevision.libraryId", "TopologyUnitRevision.id"],
            ondelete="RESTRICT",
        ),
    )

    library_id: Mapped[str] = mapped_column("libraryId", _ID, primary_key=True)
    volume_id: Mapped[str] = mapped_column("volumeId", _ID, primary_key=True)
    processor_kind: Mapped[ContentProcessorKind] = mapped_column(
        "processorKind",
        Enum(ContentProcessorKind, **_ENUM),
        primary_key=True,
    )
    work_revision: Mapped[int] = mapped_column(
        "workRevision", BigInteger, nullable=False
    )
    processor_version: Mapped[str] = mapped_column(
        "processorVersion", String(64), nullable=False
    )
    active_topology_revision_id: Mapped[str] = mapped_column(
        "activeTopologyRevisionId", _ID, nullable=False
    )
    expected_content_revision: Mapped[int] = mapped_column(
        "expectedContentRevision", BigInteger, nullable=False
    )
    expected_required_manifest_revision: Mapped[int] = mapped_column(
        "expectedRequiredManifestRevision", BigInteger, nullable=False
    )
    input_fingerprint: Mapped[str] = mapped_column(
        "inputFingerprint", _SHA256, nullable=False
    )
    available_at: Mapped[datetime] = mapped_column(
        "availableAt", DateTime(timezone=True), nullable=False
    )
    state: Mapped[ProcessorState] = mapped_column(
        Enum(ProcessorState, **_ENUM), nullable=False
    )
    failure_code: Mapped[str | None] = mapped_column("failureCode", String(96))
    lease_owner: Mapped[str | None] = mapped_column("leaseOwner", _ID)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        "leaseExpiresAt", DateTime(timezone=True)
    )
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        "updatedAt",
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        nullable=False,
    )


class SourceWriteOperation(CurrentBase):
    __tablename__ = "SourceWriteOperation"
    __table_args__ = (
        ForeignKeyConstraint(["libraryId"], ["CatalogLibrary.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["actorUserId"], ["User.id"], ondelete="SET NULL"),
        UniqueConstraint(
            "libraryId", "idempotencyKey", name="SourceWriteOperation_idempotency_key"
        ),
    )

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    library_id: Mapped[str] = mapped_column("libraryId", _ID, nullable=False)
    actor_user_id: Mapped[str | None] = mapped_column("actorUserId", _ID)
    idempotency_key: Mapped[str] = mapped_column(
        "idempotencyKey", String(191), nullable=False
    )
    organization_mode: Mapped[OrganizationMode] = mapped_column(
        "organizationMode", Enum(OrganizationMode, **_ENUM), nullable=False
    )
    destination: Mapped[str] = mapped_column(Text, nullable=False)
    target_slot_key: Mapped[str] = mapped_column("targetSlotKey", Text, nullable=False)
    state: Mapped[OperationState] = mapped_column(
        Enum(OperationState, **_ENUM), nullable=False
    )
    expected_config_revision: Mapped[int] = mapped_column(
        "expectedConfigRevision", BigInteger, nullable=False
    )
    expected_content_revision: Mapped[int | None] = mapped_column(
        "expectedContentRevision", BigInteger
    )
    staging_fence: Mapped[int] = mapped_column(
        "stagingFence", BigInteger, nullable=False, default=0
    )
    cancel_requested_at: Mapped[datetime | None] = mapped_column(
        "cancelRequestedAt", DateTime(timezone=True)
    )
    owner_token: Mapped[str | None] = mapped_column("ownerToken", _ID)
    heartbeat_at: Mapped[datetime | None] = mapped_column(
        "heartbeatAt", DateTime(timezone=True)
    )
    temporary_structure: Mapped[dict[str, object]] = mapped_column(
        "temporaryStructure", JSON, nullable=False, default=dict
    )
    final_structure: Mapped[dict[str, object]] = mapped_column(
        "finalStructure", JSON, nullable=False, default=dict
    )
    evidence: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    recovery_note: Mapped[str | None] = mapped_column("recoveryNote", Text)
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        "updatedAt",
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        nullable=False,
    )


class OperationStagingLock(CurrentBase):
    __tablename__ = "OperationStagingLock"
    __table_args__ = (
        ForeignKeyConstraint(
            ["operationId"], ["SourceWriteOperation.id"], ondelete="CASCADE"
        ),
    )

    operation_id: Mapped[str] = mapped_column("operationId", _ID, primary_key=True)
    owner_token: Mapped[str] = mapped_column("ownerToken", _ID, nullable=False)
    fence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    heartbeat_at: Mapped[datetime] = mapped_column(
        "heartbeatAt",
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        nullable=False,
    )
    lease_expires_at: Mapped[datetime] = mapped_column(
        "leaseExpiresAt", DateTime(timezone=True), nullable=False
    )


class CatalogOutbox(CurrentBase):
    __tablename__ = "CatalogOutbox"
    __table_args__ = (
        ForeignKeyConstraint(["libraryId"], ["CatalogLibrary.id"], ondelete="CASCADE"),
        Index("CatalogOutbox_delivery_idx", "deliveredAt", "availableAt"),
    )

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    library_id: Mapped[str | None] = mapped_column("libraryId", _ID)
    aggregate_type: Mapped[str] = mapped_column(
        "aggregateType", String(64), nullable=False
    )
    aggregate_id: Mapped[str] = mapped_column("aggregateId", _ID, nullable=False)
    event_type: Mapped[str] = mapped_column("eventType", String(96), nullable=False)
    event_version: Mapped[int] = mapped_column(
        "eventVersion", Integer, nullable=False, default=1
    )
    payload: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    available_at: Mapped[datetime] = mapped_column(
        "availableAt",
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        nullable=False,
    )
    delivered_at: Mapped[datetime | None] = mapped_column(
        "deliveredAt", DateTime(timezone=True)
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column("lastError", Text)
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        nullable=False,
    )


class AdministrativeAuditEvent(CurrentBase):
    __tablename__ = "AdministrativeAuditEvent"
    __table_args__ = (
        ForeignKeyConstraint(["actorUserId"], ["User.id"], ondelete="SET NULL"),
        ForeignKeyConstraint(
            ["operationId"], ["SourceWriteOperation.id"], ondelete="SET NULL"
        ),
        Index("AdministrativeAuditEvent_time_idx", "occurredAt"),
    )

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    former_library_id: Mapped[str | None] = mapped_column("formerLibraryId", _ID)
    operation_id: Mapped[str | None] = mapped_column("operationId", _ID)
    code: Mapped[str] = mapped_column(String(96), nullable=False)
    actor_kind: Mapped[AuditActorKind] = mapped_column(
        "actorKind", Enum(AuditActorKind, **_ENUM), nullable=False
    )
    actor_user_id: Mapped[str | None] = mapped_column("actorUserId", _ID)
    occurred_at: Mapped[datetime] = mapped_column(
        "occurredAt",
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        nullable=False,
    )
    evidence: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict
    )


# SQLAlchemy cannot reference a mapped class in a class body before the class is
# complete.  These expression constraints are still schema objects, not SQL text.
cast(Table, CatalogLibrary.__table__).append_constraint(
    CheckConstraint(
        CatalogLibrary.topology_version > 0, name="CatalogLibrary_topology_version_ck"
    )
)
cast(Table, CatalogLibrary.__table__).append_constraint(
    CheckConstraint(
        CatalogLibrary.config_revision > 0, name="CatalogLibrary_config_revision_ck"
    )
)
cast(Table, CatalogLibrary.__table__).append_constraint(
    CheckConstraint(
        CatalogLibrary.topology_writer_fence >= 0, name="CatalogLibrary_writer_fence_ck"
    )
)
cast(Table, CatalogLibrary.__table__).append_constraint(
    CheckConstraint(
        CatalogLibrary.source_mutation_fence >= 0,
        name="CatalogLibrary_mutation_fence_ck",
    )
)
cast(Table, CatalogLibrary.__table__).append_constraint(
    CheckConstraint(
        CatalogLibrary.next_scan_generation > 0,
        name="CatalogLibrary_scan_generation_ck",
    )
)
cast(Table, LibraryWatcherState.__table__).append_constraint(
    CheckConstraint(
        LibraryWatcherState.latest_sequence >= 0,
        name="LibraryWatcherState_latest_sequence_ck",
    )
)
cast(Table, LibraryWatcherState.__table__).append_constraint(
    CheckConstraint(
        or_(
            and_(
                LibraryWatcherState.overflow_through_sequence.is_(None),
                LibraryWatcherState.full_rescan_reason.is_(None),
            ),
            and_(
                LibraryWatcherState.overflow_through_sequence.is_not(None),
                LibraryWatcherState.overflow_through_sequence > 0,
                LibraryWatcherState.overflow_through_sequence
                <= LibraryWatcherState.latest_sequence,
                LibraryWatcherState.full_rescan_reason.is_not(None),
            ),
        ),
        name="LibraryWatcherState_overflow_shape_ck",
    )
)
cast(Table, LibraryReconcileIntent.__table__).append_constraint(
    CheckConstraint(
        and_(
            LibraryReconcileIntent.first_sequence > 0,
            LibraryReconcileIntent.through_sequence
            >= LibraryReconcileIntent.first_sequence,
            LibraryReconcileIntent.attempt >= 0,
            LibraryReconcileIntent.config_revision > 0,
            LibraryReconcileIntent.topology_version > 0,
        ),
        name="LibraryReconcileIntent_positive_ck",
    )
)
cast(Table, LibraryReconcileIntent.__table__).append_constraint(
    CheckConstraint(
        or_(
            and_(
                LibraryReconcileIntent.scope2_path.is_(None),
                LibraryReconcileIntent.scope2_key.is_(None),
            ),
            and_(
                LibraryReconcileIntent.scope2_path.is_not(None),
                LibraryReconcileIntent.scope2_key.is_not(None),
            ),
        ),
        name="LibraryReconcileIntent_scope_shape_ck",
    )
)
cast(Table, LibraryReconcileIntent.__table__).append_constraint(
    CheckConstraint(
        or_(
            and_(
                LibraryReconcileIntent.move_old_path.is_(None),
                LibraryReconcileIntent.move_new_path.is_(None),
                LibraryReconcileIntent.moved_entry_type.is_(None),
            ),
            and_(
                LibraryReconcileIntent.move_old_path.is_not(None),
                LibraryReconcileIntent.move_new_path.is_not(None),
                LibraryReconcileIntent.moved_entry_type.is_not(None),
            ),
        ),
        name="LibraryReconcileIntent_move_shape_ck",
    )
)
cast(Table, LibraryReconcileIntent.__table__).append_constraint(
    CheckConstraint(
        or_(
            and_(
                LibraryReconcileIntent.state == ReconcileIntentState.PENDING,
                LibraryReconcileIntent.lease_owner.is_(None),
                LibraryReconcileIntent.lease_expires_at.is_(None),
                LibraryReconcileIntent.topology_writer_fence.is_(None),
            ),
            and_(
                LibraryReconcileIntent.state == ReconcileIntentState.RUNNING,
                LibraryReconcileIntent.lease_owner.is_not(None),
                LibraryReconcileIntent.lease_expires_at.is_not(None),
                LibraryReconcileIntent.topology_writer_fence > 0,
            ),
        ),
        name="LibraryReconcileIntent_lease_shape_ck",
    )
)
cast(Table, LibraryReconcileIntent.__table__).append_constraint(
    CheckConstraint(
        or_(
            and_(
                LibraryReconcileIntent.phase == ReconcileIntentPhase.EXECUTE,
                LibraryReconcileIntent.fold_after_source_entry_id.is_(None),
            ),
            LibraryReconcileIntent.phase == ReconcileIntentPhase.FOLD,
        ),
        name="LibraryReconcileIntent_phase_shape_ck",
    )
)
Index(
    "LibraryReconcileIntent_one_pending_key_idx",
    LibraryReconcileIntent.library_id,
    LibraryReconcileIntent.coalesce_key,
    unique=True,
    sqlite_where=LibraryReconcileIntent.state == ReconcileIntentState.PENDING,
)
Index(
    "LibraryReconcileIntent_one_running_idx",
    LibraryReconcileIntent.library_id,
    unique=True,
    sqlite_where=LibraryReconcileIntent.state == ReconcileIntentState.RUNNING,
)
cast(Table, LibraryRootRegistryLock.__table__).append_constraint(
    CheckConstraint(
        LibraryRootRegistryLock.id == 1, name="LibraryRootRegistryLock_singleton_ck"
    )
)
cast(Table, LibrarySourceEntry.__table__).append_constraint(
    CheckConstraint(
        or_(
            LibrarySourceEntry.entry_type != SourceEntryType.SYNTHETIC_ROOT,
            and_(
                LibrarySourceEntry.parent_entry_id.is_(None),
                LibrarySourceEntry.local_name == "$root",
            ),
        ),
        name="LibrarySourceEntry_root_shape_ck",
    )
)
cast(Table, LibrarySourceEntry.__table__).append_constraint(
    CheckConstraint(
        and_(
            LibrarySourceEntry.children_presence_epoch >= 0,
            LibrarySourceEntry.next_children_presence_epoch
            >= LibrarySourceEntry.children_presence_epoch,
            or_(
                LibrarySourceEntry.observed_parent_presence_epoch.is_(None),
                LibrarySourceEntry.observed_parent_presence_epoch >= 0,
            ),
            or_(
                LibrarySourceEntry.pending_observed_parent_presence_epoch.is_(None),
                LibrarySourceEntry.pending_observed_parent_presence_epoch > 0,
            ),
        ),
        name="LibrarySourceEntry_presence_epoch_ck",
    )
)
cast(Table, LibrarySourceEntry.__table__).append_constraint(
    CheckConstraint(
        or_(
            LibrarySourceEntry.entry_type == SourceEntryType.SYNTHETIC_ROOT,
            LibrarySourceEntry.parent_entry_id.is_not(None),
        ),
        name="LibrarySourceEntry_parent_required_ck",
    )
)
Index(
    "LibrarySourceEntry_one_root_idx",
    LibrarySourceEntry.library_id,
    unique=True,
    sqlite_where=LibrarySourceEntry.entry_type == SourceEntryType.SYNTHETIC_ROOT,
)
Index(
    "LibrarySourceEntry_active_slot_idx",
    LibrarySourceEntry.library_id,
    LibrarySourceEntry.parent_entry_id,
    LibrarySourceEntry.local_name_key,
    unique=True,
    sqlite_where=LibrarySourceEntry.slot_state == SlotState.ACTIVE,
)
Index(
    "LibrarySourceEntry_live_raw_slot_idx",
    LibrarySourceEntry.library_id,
    LibrarySourceEntry.parent_entry_id,
    LibrarySourceEntry.local_name,
    unique=True,
    sqlite_where=LibrarySourceEntry.slot_state != SlotState.RETIRED,
)
Index(
    "LibrarySourceEntry_generation_idx",
    LibrarySourceEntry.library_id,
    LibrarySourceEntry.last_seen_generation,
)
Index(
    "LibrarySourceEntry_pending_presence_idx",
    LibrarySourceEntry.library_id,
    LibrarySourceEntry.parent_entry_id,
    LibrarySourceEntry.pending_observed_parent_presence_epoch,
    LibrarySourceEntry.id,
)
Index(
    "LibrarySourceEntry_identity_idx",
    LibrarySourceEntry.library_id,
    LibrarySourceEntry.filesystem_identity,
)
Index(
    "LibrarySourceEntry_raw_slot_idx",
    LibrarySourceEntry.library_id,
    LibrarySourceEntry.parent_entry_id,
    LibrarySourceEntry.local_name,
)
Index(
    "LibraryScanRun_one_active_idx",
    LibraryScanRun.library_id,
    unique=True,
    sqlite_where=LibraryScanRun.state.in_(
        [ScanState.PENDING, ScanState.RUNNING, ScanState.FINALIZING]
    ),
)
cast(Table, LibraryScanRun.__table__).append_constraint(
    CheckConstraint(
        LibraryScanRun.watcher_sequence_watermark >= 0,
        name="LibraryScanRun_watcher_watermark_ck",
    )
)
cast(Table, LayoutDiagnostic.__table__).append_constraint(
    CheckConstraint(
        (
            (LayoutDiagnostic.scan_run_id.is_not(None)).cast(Integer)
            + (LayoutDiagnostic.reconcile_origin_id.is_not(None)).cast(Integer)
            == 1
        ),
        name="LayoutDiagnostic_origin_ck",
    )
)
Index(
    "LayoutDiagnostic_reconcile_origin_idx",
    LayoutDiagnostic.library_id,
    LayoutDiagnostic.reconcile_origin_id,
)
cast(Table, SourceAttachment.__table__).append_constraint(
    CheckConstraint(
        (
            (SourceAttachment.work_id.is_not(None)).cast(Integer)
            + (SourceAttachment.version_id.is_not(None)).cast(Integer)
            + (SourceAttachment.volume_id.is_not(None)).cast(Integer)
            == 1
        ),
        name="SourceAttachment_one_owner_ck",
    )
)
cast(Table, TopologyUnit.__table__).append_constraint(
    CheckConstraint(
        (
            (TopologyUnit.work_owner_id.is_not(None)).cast(Integer)
            + (TopologyUnit.version_owner_id.is_not(None)).cast(Integer)
            + (TopologyUnit.volume_owner_id.is_not(None)).cast(Integer)
            == 1
        ),
        name="TopologyUnit_one_owner_ck",
    )
)
cast(Table, TopologyUnit.__table__).append_constraint(
    CheckConstraint(
        or_(
            and_(
                TopologyUnit.unit_kind.in_(
                    [TopologyUnitKind.WORK_CONTAINER, TopologyUnitKind.AUDIOBOOK_WORK]
                ),
                TopologyUnit.work_owner_id.is_not(None),
                TopologyUnit.version_owner_id.is_(None),
                TopologyUnit.volume_owner_id.is_(None),
            ),
            and_(
                TopologyUnit.unit_kind == TopologyUnitKind.VERSION_CONTAINER,
                TopologyUnit.work_owner_id.is_(None),
                TopologyUnit.version_owner_id.is_not(None),
                TopologyUnit.volume_owner_id.is_(None),
            ),
            and_(
                TopologyUnit.unit_kind.in_(
                    [
                        TopologyUnitKind.FLAT_VOLUME,
                        TopologyUnitKind.SINGLE_FILE_VOLUME,
                        TopologyUnitKind.MULTI_ASSET_VOLUME,
                    ]
                ),
                TopologyUnit.work_owner_id.is_(None),
                TopologyUnit.version_owner_id.is_(None),
                TopologyUnit.volume_owner_id.is_not(None),
            ),
        ),
        name="TopologyUnit_owner_kind_ck",
    )
)
Index(
    "TopologyUnit_work_owner_idx",
    TopologyUnit.library_id,
    TopologyUnit.work_owner_id,
    unique=True,
    sqlite_where=TopologyUnit.work_owner_id.is_not(None),
)
Index(
    "TopologyUnit_version_owner_idx",
    TopologyUnit.library_id,
    TopologyUnit.version_owner_id,
    unique=True,
    sqlite_where=TopologyUnit.version_owner_id.is_not(None),
)
Index(
    "TopologyUnit_volume_owner_idx",
    TopologyUnit.library_id,
    TopologyUnit.volume_owner_id,
    unique=True,
    sqlite_where=TopologyUnit.volume_owner_id.is_not(None),
)
cast(Table, TopologyUnitRevision.__table__).append_constraint(
    CheckConstraint(
        TopologyUnitRevision.revision > 0, name="TopologyUnitRevision_revision_ck"
    )
)
cast(Table, TopologyUnitRevision.__table__).append_constraint(
    CheckConstraint(
        (
            (TopologyUnitRevision.scan_run_id.is_not(None)).cast(Integer)
            + (TopologyUnitRevision.reconcile_origin_id.is_not(None)).cast(Integer)
            == 1
        ),
        name="TopologyUnitRevision_origin_ck",
    )
)
Index(
    "TopologyUnitRevision_reconcile_origin_idx",
    TopologyUnitRevision.library_id,
    TopologyUnitRevision.reconcile_origin_id,
    TopologyUnitRevision.state,
)
Index(
    "TopologyUnitRevision_one_active_idx",
    TopologyUnitRevision.library_id,
    TopologyUnitRevision.unit_id,
    unique=True,
    sqlite_where=TopologyUnitRevision.state == RevisionState.ACTIVE,
)
cast(Table, TopologyVersionProjection.__table__).append_constraint(
    CheckConstraint(
        or_(
            and_(
                TopologyVersionProjection.kind == VersionKind.IMPLICIT,
                TopologyVersionProjection.root_entry_id.is_(None),
                TopologyVersionProjection.source_name.is_(None),
            ),
            and_(
                TopologyVersionProjection.kind == VersionKind.DIRECTORY,
                TopologyVersionProjection.root_entry_id.is_not(None),
                TopologyVersionProjection.source_name.is_not(None),
            ),
        ),
        name="TopologyVersionProjection_shape_ck",
    )
)
cast(Table, TopologyAssetMembership.__table__).append_constraint(
    CheckConstraint(
        TopologyAssetMembership.asset_order >= 0,
        name="TopologyAssetMembership_order_ck",
    )
)
cast(Table, TopologyAssetMembership.__table__).append_constraint(
    CheckConstraint(
        TopologyAssetMembership.disc_number.is_(None)
        | (TopologyAssetMembership.disc_number >= 1),
        name="TopologyAssetMembership_disc_ck",
    )
)
cast(Table, LibraryVolume.__table__).append_constraint(
    CheckConstraint(
        and_(
            LibraryVolume.content_revision >= 0,
            LibraryVolume.required_manifest_revision >= 0,
            LibraryVolume.optional_manifest_revision >= 0,
            LibraryVolume.metadata_revision >= 0,
            or_(
                and_(
                    LibraryVolume.content_revision == 0,
                    LibraryVolume.required_manifest_revision == 0,
                ),
                and_(
                    LibraryVolume.content_revision > 0,
                    LibraryVolume.required_manifest_revision > 0,
                ),
            ),
        ),
        name="LibraryVolume_revision_vector_ck",
    )
)
cast(Table, LibraryVolume.__table__).append_constraint(
    CheckConstraint(
        or_(
            LibraryVolume.publication_fingerprint.is_(None),
            and_(
                func.length(LibraryVolume.publication_fingerprint) == 71,
                LibraryVolume.publication_fingerprint.regexp_match(
                    r"^sha256:[0-9a-f]{64}$"
                ),
            ),
        ),
        name="LibraryVolume_publication_fingerprint_ck",
    )
)
cast(Table, LibraryVolume.__table__).append_constraint(
    CheckConstraint(
        or_(
            LibraryVolume.content_state != VolumeContentState.READY,
            LibraryVolume.publication_fingerprint.is_not(None),
        ),
        name="LibraryVolume_ready_fingerprint_ck",
    )
)
cast(Table, LibraryVolume.__table__).append_constraint(
    CheckConstraint(
        or_(
            and_(
                LibraryVolume.required_manifest_revision == 0,
                LibraryVolume.required_manifest_digest.is_(None),
            ),
            and_(
                LibraryVolume.required_manifest_revision > 0,
                LibraryVolume.required_manifest_digest.is_not(None),
                func.length(LibraryVolume.required_manifest_digest) == 71,
                LibraryVolume.required_manifest_digest.regexp_match(
                    r"^sha256:[0-9a-f]{64}$"
                ),
            ),
        ),
        name="LibraryVolume_required_revision_shape_ck",
    )
)
cast(Table, ContentTopologyProjectionState.__table__).append_constraint(
    CheckConstraint(
        and_(
            ContentTopologyProjectionState.applied_epoch >= 0,
            ContentTopologyProjectionState.applied_epoch
            <= ContentTopologyProjectionState.claimed_epoch,
            ContentTopologyProjectionState.claimed_epoch
            <= ContentTopologyProjectionState.requested_epoch,
            or_(
                ContentTopologyProjectionState.applied_epoch
                != ContentTopologyProjectionState.claimed_epoch,
                ContentTopologyProjectionState.cursor_volume_id.is_(None),
            ),
        ),
        name="ContentTopologyProjectionState_epoch_ck",
    )
)
cast(Table, SourceContentFact.__table__).append_constraint(
    CheckConstraint(
        and_(
            SourceContentFact.input_revision > 0,
            or_(
                SourceContentFact.digest_input_revision.is_(None),
                and_(
                    SourceContentFact.digest_input_revision > 0,
                    SourceContentFact.digest_input_revision
                    <= SourceContentFact.input_revision,
                ),
            ),
            SourceContentFact.device_id >= 0,
            SourceContentFact.file_id >= 0,
            SourceContentFact.size_bytes >= 0,
            SourceContentFact.policy_version > 0,
            SourceContentFact.work_revision >= 0,
            SourceContentFact.origin_sequence > 0,
        ),
        name="SourceContentFact_positive_ck",
    )
)
cast(Table, SourceContentFact.__table__).append_constraint(
    CheckConstraint(
        or_(
            and_(
                SourceContentFact.origin_kind == ContentOriginKind.WATCHER,
                SourceContentFact.origin_id.is_(None),
            ),
            and_(
                SourceContentFact.origin_kind.in_(
                    (ContentOriginKind.FULL_SCAN, ContentOriginKind.RECONCILE)
                ),
                SourceContentFact.origin_id.is_not(None),
            ),
        ),
        name="SourceContentFact_origin_shape_ck",
    )
)
cast(Table, SourceContentFact.__table__).append_constraint(
    CheckConstraint(
        or_(
            and_(
                SourceContentFact.content_digest.is_(None),
                SourceContentFact.digest_input_revision.is_(None),
            ),
            and_(
                SourceContentFact.content_digest.is_not(None),
                SourceContentFact.digest_input_revision.is_not(None),
                func.length(SourceContentFact.content_digest) == 71,
                SourceContentFact.content_digest.regexp_match(r"^sha256:[0-9a-f]{64}$"),
            ),
        ),
        name="SourceContentFact_digest_shape_ck",
    )
)
cast(Table, SourceContentFact.__table__).append_constraint(
    CheckConstraint(
        or_(
            and_(
                or_(
                    and_(
                        SourceContentFact.admission == "PRIMARY",
                        SourceContentFact.source_format.in_(
                            (
                                "EPUB",
                                "MOBI",
                                "AZW",
                                "AZW3",
                                "PRC",
                                "TXT",
                                "PDF",
                                "CBZ",
                                "CBR",
                                "RAR",
                                "ZIP",
                            )
                        ),
                    ),
                    and_(
                        SourceContentFact.admission == "AUDIO_TRACK",
                        SourceContentFact.source_format.in_(("MP3", "M4A", "M4B")),
                    ),
                ),
                SourceContentFact.state != SourceContentState.INELIGIBLE,
            ),
            and_(
                SourceContentFact.admission.in_(("SIDECAR", "UNSUPPORTED", "IGNORED")),
                SourceContentFact.source_format.is_(None),
                SourceContentFact.state == SourceContentState.INELIGIBLE,
                SourceContentFact.content_digest.is_(None),
                SourceContentFact.digest_input_revision.is_(None),
            ),
        ),
        name="SourceContentFact_admission_shape_ck",
    )
)
cast(Table, SourceContentFact.__table__).append_constraint(
    CheckConstraint(
        or_(
            and_(
                SourceContentFact.state == SourceContentState.PENDING,
                SourceContentFact.lease_owner.is_(None),
                SourceContentFact.lease_expires_at.is_(None),
            ),
            and_(
                SourceContentFact.state == SourceContentState.RUNNING,
                SourceContentFact.lease_owner.is_not(None),
                SourceContentFact.lease_expires_at.is_not(None),
            ),
            and_(
                SourceContentFact.state == SourceContentState.READY,
                SourceContentFact.lease_owner.is_(None),
                SourceContentFact.lease_expires_at.is_(None),
                SourceContentFact.content_digest.is_not(None),
                SourceContentFact.digest_input_revision
                == SourceContentFact.input_revision,
            ),
            and_(
                SourceContentFact.state == SourceContentState.INELIGIBLE,
                SourceContentFact.lease_owner.is_(None),
                SourceContentFact.lease_expires_at.is_(None),
            ),
        ),
        name="SourceContentFact_state_shape_ck",
    )
)
Index(
    "SourceContentFact_claim_idx",
    SourceContentFact.state,
    SourceContentFact.available_at,
    SourceContentFact.library_id,
    SourceContentFact.source_entry_id,
)
cast(Table, VolumeManifestHeader.__table__).append_constraint(
    CheckConstraint(
        and_(
            VolumeManifestHeader.processing_revision > 0,
            func.length(func.trim(VolumeManifestHeader.processor_version)) > 0,
            VolumeManifestHeader.topology_version > 0,
            VolumeManifestHeader.delivery_policy_version > 0,
            VolumeManifestHeader.base_content_revision >= 0,
            VolumeManifestHeader.base_required_manifest_revision >= 0,
            or_(
                and_(
                    VolumeManifestHeader.base_content_revision == 0,
                    VolumeManifestHeader.base_required_manifest_revision == 0,
                ),
                and_(
                    VolumeManifestHeader.base_content_revision > 0,
                    VolumeManifestHeader.base_required_manifest_revision > 0,
                ),
            ),
            VolumeManifestHeader.expected_entry_count.between(1, 10_000),
            VolumeManifestHeader.staged_entry_count >= 0,
            VolumeManifestHeader.staged_entry_count
            <= VolumeManifestHeader.expected_entry_count,
        ),
        name="VolumeManifestHeader_bounds_ck",
    )
)
cast(Table, VolumeManifestHeader.__table__).append_constraint(
    CheckConstraint(
        or_(
            and_(
                VolumeManifestHeader.published_content_revision.is_(None),
                VolumeManifestHeader.published_required_manifest_revision.is_(None),
            ),
            and_(
                VolumeManifestHeader.published_content_revision > 0,
                VolumeManifestHeader.published_required_manifest_revision > 0,
                VolumeManifestHeader.published_required_manifest_revision
                == VolumeManifestHeader.base_required_manifest_revision + 1,
                VolumeManifestHeader.published_content_revision.in_(
                    (
                        VolumeManifestHeader.base_content_revision,
                        VolumeManifestHeader.base_content_revision + 1,
                    )
                ),
                or_(
                    VolumeManifestHeader.base_content_revision > 0,
                    VolumeManifestHeader.published_content_revision == 1,
                ),
            ),
        ),
        name="VolumeManifestHeader_published_vector_ck",
    )
)
cast(Table, VolumeManifestHeader.__table__).append_constraint(
    CheckConstraint(
        and_(
            func.length(VolumeManifestHeader.source_bytes_digest) == 71,
            VolumeManifestHeader.source_bytes_digest.regexp_match(
                r"^sha256:[0-9a-f]{64}$"
            ),
            func.length(VolumeManifestHeader.content_facts_digest) == 71,
            VolumeManifestHeader.content_facts_digest.regexp_match(
                r"^sha256:[0-9a-f]{64}$"
            ),
            func.length(VolumeManifestHeader.delivery_facts_digest) == 71,
            VolumeManifestHeader.delivery_facts_digest.regexp_match(
                r"^sha256:[0-9a-f]{64}$"
            ),
        ),
        name="VolumeManifestHeader_digest_shape_ck",
    )
)
cast(Table, VolumeManifestHeader.__table__).append_constraint(
    CheckConstraint(
        or_(
            and_(
                VolumeManifestHeader.state == RequiredManifestState.STAGING,
                VolumeManifestHeader.published_content_revision.is_(None),
                VolumeManifestHeader.published_required_manifest_revision.is_(None),
                VolumeManifestHeader.activated_at.is_(None),
            ),
            and_(
                VolumeManifestHeader.state == RequiredManifestState.ACTIVE,
                VolumeManifestHeader.staged_entry_count
                == VolumeManifestHeader.expected_entry_count,
                VolumeManifestHeader.published_content_revision.is_not(None),
                VolumeManifestHeader.published_required_manifest_revision.is_not(None),
                VolumeManifestHeader.activated_at.is_not(None),
            ),
        ),
        name="VolumeManifestHeader_state_shape_ck",
    )
)
Index(
    "VolumeManifestHeader_one_active_idx",
    VolumeManifestHeader.library_id,
    VolumeManifestHeader.volume_id,
    VolumeManifestHeader.kind,
    unique=True,
    sqlite_where=VolumeManifestHeader.state == RequiredManifestState.ACTIVE,
)
Index(
    "VolumeManifestHeader_one_staging_idx",
    VolumeManifestHeader.library_id,
    VolumeManifestHeader.volume_id,
    VolumeManifestHeader.kind,
    unique=True,
    sqlite_where=VolumeManifestHeader.state == RequiredManifestState.STAGING,
)
Index(
    "VolumeManifestHeader_reader_idx",
    VolumeManifestHeader.library_id,
    VolumeManifestHeader.volume_id,
    VolumeManifestHeader.kind,
    VolumeManifestHeader.state,
    VolumeManifestHeader.id,
)
cast(Table, VolumeManifestEntry.__table__).append_constraint(
    CheckConstraint(
        and_(
            VolumeManifestEntry.source_fact_revision > 0,
            VolumeManifestEntry.size_bytes >= 0,
            VolumeManifestEntry.asset_order.between(0, 9_999),
            VolumeManifestEntry.role.in_((AssetRole.PRIMARY, AssetRole.AUDIO_TRACK)),
            VolumeManifestEntry.mime_type.regexp_match(
                r"^[a-z0-9!#$&^_.+-]+/[a-z0-9!#$&^_.+-]+$"
            ),
            func.length(VolumeManifestEntry.content_digest) == 71,
            VolumeManifestEntry.content_digest.regexp_match(r"^sha256:[0-9a-f]{64}$"),
        ),
        name="VolumeManifestEntry_shape_ck",
    )
)
cast(Table, VolumeProcessingFact.__table__).append_constraint(
    CheckConstraint(
        and_(
            VolumeProcessingFact.work_revision > 0,
            func.length(func.trim(VolumeProcessingFact.processor_version)) > 0,
            VolumeProcessingFact.expected_content_revision >= 0,
            VolumeProcessingFact.expected_required_manifest_revision >= 0,
            func.length(VolumeProcessingFact.input_fingerprint) == 71,
            VolumeProcessingFact.input_fingerprint.regexp_match(
                r"^sha256:[0-9a-f]{64}$"
            ),
        ),
        name="VolumeProcessingFact_revision_vector_ck",
    )
)
cast(Table, VolumeProcessingFact.__table__).append_constraint(
    CheckConstraint(
        or_(
            and_(
                VolumeProcessingFact.state == ProcessorState.PENDING,
                VolumeProcessingFact.lease_owner.is_(None),
                VolumeProcessingFact.lease_expires_at.is_(None),
                VolumeProcessingFact.failure_code.is_(None),
            ),
            and_(
                VolumeProcessingFact.state == ProcessorState.RUNNING,
                VolumeProcessingFact.lease_owner.is_not(None),
                VolumeProcessingFact.lease_expires_at.is_not(None),
                VolumeProcessingFact.failure_code.is_(None),
            ),
            and_(
                VolumeProcessingFact.state == ProcessorState.READY,
                VolumeProcessingFact.lease_owner.is_(None),
                VolumeProcessingFact.lease_expires_at.is_(None),
                VolumeProcessingFact.failure_code.is_(None),
            ),
            and_(
                VolumeProcessingFact.state == ProcessorState.FAILED,
                VolumeProcessingFact.lease_owner.is_(None),
                VolumeProcessingFact.lease_expires_at.is_(None),
                VolumeProcessingFact.failure_code.is_not(None),
            ),
        ),
        name="VolumeProcessingFact_state_shape_ck",
    )
)
Index(
    "VolumeProcessingFact_claim_idx",
    VolumeProcessingFact.library_id,
    VolumeProcessingFact.processor_kind,
    VolumeProcessingFact.state,
    VolumeProcessingFact.available_at,
    VolumeProcessingFact.volume_id,
)
cast(Table, SourceWriteOperation.__table__).append_constraint(
    CheckConstraint(
        SourceWriteOperation.expected_config_revision > 0,
        name="SourceWriteOperation_config_revision_ck",
    )
)
Index(
    "SourceWriteOperation_active_slot_idx",
    SourceWriteOperation.library_id,
    SourceWriteOperation.target_slot_key,
    unique=True,
    sqlite_where=~SourceWriteOperation.state.in_(
        [
            OperationState.COMPLETED,
            OperationState.CANCELLED,
            OperationState.ABANDONED_BY_LIBRARY_REMOVAL,
            OperationState.FAILED,
        ]
    ),
)


__all__ = [
    "AdministrativeAuditEvent",
    "CatalogLibrary",
    "CatalogOutbox",
    "ContentTopologyProjectionState",
    "LayoutDiagnostic",
    "LibraryIgnoreRule",
    "LibraryReconcileIntent",
    "LibraryRootRegistryLock",
    "LibraryScanRun",
    "LibraryScanWorkItem",
    "LibrarySourceEntry",
    "LibraryVolume",
    "LibraryWatcherState",
    "LibraryWork",
    "OperationStagingLock",
    "PathCollisionObservation",
    "SourceAttachment",
    "SourceContentFact",
    "SourceWriteOperation",
    "TopologyAssetMembership",
    "TopologyUnit",
    "TopologyUnitRevision",
    "TopologyVersionProjection",
    "TopologyVolumeProjection",
    "TopologyWorkProjection",
    "UserLibraryGrant",
    "VolumeAsset",
    "VolumeManifestEntry",
    "VolumeManifestHeader",
    "VolumeProcessingFact",
    "WorkVersion",
]
