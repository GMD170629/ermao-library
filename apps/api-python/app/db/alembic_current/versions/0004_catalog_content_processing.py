"""Add bounded source-content and required-manifest processing state.

The current lineage supports empty fresh installs only. This revision therefore
contains schema operations only: no compatibility reads, backfill, or runtime
model imports.
"""

from __future__ import annotations

from collections.abc import Sequence
from importlib import import_module
from types import ModuleType
from typing import cast

from alembic import context, op
from sqlalchemy import (
    BigInteger,
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
    UniqueConstraint,
    and_,
    column,
    func,
    or_,
)

revision: str = "0004_catalog_content_processing"
down_revision: str | None = "0003_catalog_watcher_reconcile"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ID = String(191)
_SHA256 = String(71)
_DT = DateTime(timezone=True)
_SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"

_baseline_revision = cast(
    ModuleType,
    import_module("app.db.alembic_current.versions.0001_system_and_catalog_core"),
)
_baseline_metadata = cast(MetaData, _baseline_revision.metadata)


def _enum(name: str, *values: str) -> Enum:
    return Enum(*values, name=name, native_enum=False, create_constraint=True)


def _offline_library_volume_copy() -> Table | None:
    if not context.is_offline_mode():
        return None
    return _baseline_metadata.tables["LibraryVolume"]


def _extend_library_volume() -> None:
    content_revision = column("contentRevision", BigInteger)
    required_revision = column("requiredManifestRevision", BigInteger)
    optional_revision = column("optionalManifestRevision", BigInteger)
    metadata_revision = column("metadataRevision", BigInteger)
    required_digest = column("requiredManifestDigest", String(191))
    publication_fingerprint = column("publicationFingerprint", String(191))

    with op.batch_alter_table(
        "LibraryVolume",
        recreate="always",
        copy_from=_offline_library_volume_copy(),
    ) as batch_op:
        batch_op.alter_column(
            "contentState",
            existing_type=String(32),
            type_=_enum("volumecontentstate", "PENDING", "READY", "UNREADABLE"),
            existing_nullable=False,
        )
        batch_op.create_check_constraint(
            "LibraryVolume_revision_vector_ck",
            and_(
                content_revision >= 0,
                required_revision >= 0,
                optional_revision >= 0,
                metadata_revision >= 0,
                or_(
                    and_(content_revision == 0, required_revision == 0),
                    and_(content_revision > 0, required_revision > 0),
                ),
            ),
        )
        batch_op.create_check_constraint(
            "LibraryVolume_publication_fingerprint_ck",
            or_(
                publication_fingerprint.is_(None),
                and_(
                    func.length(publication_fingerprint) == 71,
                    publication_fingerprint.regexp_match(_SHA256_PATTERN),
                ),
            ),
        )
        batch_op.create_check_constraint(
            "LibraryVolume_ready_fingerprint_ck",
            or_(
                column("contentState", String(32)) != "READY",
                publication_fingerprint.is_not(None),
            ),
        )
        batch_op.create_check_constraint(
            "LibraryVolume_required_revision_shape_ck",
            or_(
                and_(
                    required_revision == 0,
                    required_digest.is_(None),
                ),
                and_(
                    required_revision > 0,
                    required_digest.is_not(None),
                    func.length(required_digest) == 71,
                    required_digest.regexp_match(_SHA256_PATTERN),
                ),
            ),
        )


def _create_content_topology_projection_state() -> None:
    requested_epoch = column("requestedEpoch", BigInteger)
    claimed_epoch = column("claimedEpoch", BigInteger)
    applied_epoch = column("appliedEpoch", BigInteger)
    cursor_volume_id = column("cursorVolumeId", _ID)
    state = op.create_table(
        "ContentTopologyProjectionState",
        Column("libraryId", _ID, primary_key=True),
        Column("requestedEpoch", BigInteger, nullable=False),
        Column("claimedEpoch", BigInteger, nullable=False),
        Column("appliedEpoch", BigInteger, nullable=False),
        Column("cursorVolumeId", _ID),
        Column(
            "updatedAt",
            _DT,
            nullable=False,
            server_default=func.current_timestamp(),
        ),
        ForeignKeyConstraint(
            ["libraryId"],
            ["CatalogLibrary.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint(
            and_(
                applied_epoch >= 0,
                applied_epoch <= claimed_epoch,
                claimed_epoch <= requested_epoch,
                or_(
                    applied_epoch != claimed_epoch,
                    cursor_volume_id.is_(None),
                ),
            ),
            name="ContentTopologyProjectionState_epoch_ck",
        ),
    )
    Index(
        "ContentTopologyProjectionState_pending_idx",
        state.c.requestedEpoch,
        state.c.appliedEpoch,
        state.c.libraryId,
    ).create(bind=op.get_bind())


def _create_source_content_fact() -> None:
    input_revision = column("inputRevision", BigInteger)
    work_revision = column("workRevision", BigInteger)
    digest_input_revision = column("digestInputRevision", BigInteger)
    admission = column("admission", String(16))
    source_format = column("sourceFormat", String(64))
    device_id = column("deviceId", BigInteger)
    file_id = column("fileId", BigInteger)
    size_bytes = column("sizeBytes", BigInteger)
    policy_version = column("policyVersion", Integer)
    origin_kind = column("originKind", String(9))
    origin_id = column("originId", _ID)
    origin_sequence = column("originSequence", BigInteger)
    state = column("state", String(10))
    content_digest = column("contentDigest", _SHA256)
    lease_owner = column("leaseOwner", _ID)
    lease_expires_at = column("leaseExpiresAt", _DT)

    source_content = op.create_table(
        "SourceContentFact",
        Column("libraryId", _ID, primary_key=True),
        Column("sourceEntryId", _ID, primary_key=True),
        Column("inputRevision", BigInteger, nullable=False),
        Column("workRevision", BigInteger, nullable=False),
        Column("digestInputRevision", BigInteger),
        Column("admission", String(16), nullable=False),
        Column("sourceFormat", String(64)),
        Column("filesystemIdentity", String(191), nullable=False),
        Column("deviceId", BigInteger, nullable=False),
        Column("fileId", BigInteger, nullable=False),
        Column("sizeBytes", BigInteger, nullable=False),
        Column("modifiedNs", BigInteger, nullable=False),
        Column("policyVersion", Integer, nullable=False),
        Column(
            "originKind",
            _enum("contentoriginkind", "FULL_SCAN", "RECONCILE", "WATCHER"),
            nullable=False,
        ),
        Column("originId", _ID),
        Column("originSequence", BigInteger, nullable=False),
        Column("availableAt", _DT, nullable=False),
        Column(
            "state",
            _enum(
                "sourcecontentstate",
                "PENDING",
                "RUNNING",
                "READY",
                "INELIGIBLE",
            ),
            nullable=False,
        ),
        Column("contentDigest", _SHA256),
        Column("leaseOwner", _ID),
        Column("leaseExpiresAt", _DT),
        Column(
            "createdAt",
            _DT,
            nullable=False,
            server_default=func.current_timestamp(),
        ),
        Column(
            "updatedAt",
            _DT,
            nullable=False,
            server_default=func.current_timestamp(),
        ),
        ForeignKeyConstraint(
            ["libraryId", "sourceEntryId"],
            ["LibrarySourceEntry.libraryId", "LibrarySourceEntry.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint(
            and_(
                input_revision > 0,
                or_(
                    digest_input_revision.is_(None),
                    and_(
                        digest_input_revision > 0,
                        digest_input_revision <= input_revision,
                    ),
                ),
                device_id >= 0,
                file_id >= 0,
                size_bytes >= 0,
                policy_version > 0,
                work_revision >= 0,
                origin_sequence > 0,
            ),
            name="SourceContentFact_positive_ck",
        ),
        CheckConstraint(
            or_(
                and_(origin_kind == "WATCHER", origin_id.is_(None)),
                and_(
                    origin_kind.in_(("FULL_SCAN", "RECONCILE")),
                    origin_id.is_not(None),
                ),
            ),
            name="SourceContentFact_origin_shape_ck",
        ),
        CheckConstraint(
            or_(
                and_(
                    content_digest.is_(None),
                    digest_input_revision.is_(None),
                ),
                and_(
                    content_digest.is_not(None),
                    digest_input_revision.is_not(None),
                    func.length(content_digest) == 71,
                    content_digest.regexp_match(_SHA256_PATTERN),
                ),
            ),
            name="SourceContentFact_digest_shape_ck",
        ),
        CheckConstraint(
            or_(
                and_(
                    or_(
                        and_(
                            admission == "PRIMARY",
                            source_format.in_(
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
                            admission == "AUDIO_TRACK",
                            source_format.in_(("MP3", "M4A", "M4B")),
                        ),
                    ),
                    state != "INELIGIBLE",
                ),
                and_(
                    admission.in_(("SIDECAR", "UNSUPPORTED", "IGNORED")),
                    source_format.is_(None),
                    state == "INELIGIBLE",
                    content_digest.is_(None),
                    digest_input_revision.is_(None),
                ),
            ),
            name="SourceContentFact_admission_shape_ck",
        ),
        CheckConstraint(
            or_(
                and_(
                    state == "PENDING",
                    lease_owner.is_(None),
                    lease_expires_at.is_(None),
                ),
                and_(
                    state == "RUNNING",
                    lease_owner.is_not(None),
                    lease_expires_at.is_not(None),
                ),
                and_(
                    state == "READY",
                    lease_owner.is_(None),
                    lease_expires_at.is_(None),
                    content_digest.is_not(None),
                    digest_input_revision == input_revision,
                ),
                and_(
                    state == "INELIGIBLE",
                    lease_owner.is_(None),
                    lease_expires_at.is_(None),
                ),
            ),
            name="SourceContentFact_state_shape_ck",
        ),
    )
    Index(
        "SourceContentFact_claim_idx",
        source_content.c.state,
        source_content.c.availableAt,
        source_content.c.libraryId,
        source_content.c.sourceEntryId,
    ).create(bind=op.get_bind())


def _create_manifest_tables() -> None:
    state = column("state", String(10))
    processor_version = column("processorVersion", String(64))
    processing_revision = column("processingRevision", BigInteger)
    topology_version = column("topologyVersion", Integer)
    delivery_policy_version = column("deliveryPolicyVersion", Integer)
    base_content_revision = column("baseContentRevision", BigInteger)
    base_required_revision = column("baseRequiredManifestRevision", BigInteger)
    published_content_revision = column("publishedContentRevision", BigInteger)
    published_required_revision = column(
        "publishedRequiredManifestRevision", BigInteger
    )
    expected_entry_count = column("expectedEntryCount", Integer)
    staged_entry_count = column("stagedEntryCount", Integer)
    source_bytes_digest = column("sourceBytesDigest", _SHA256)
    content_facts_digest = column("contentFactsDigest", _SHA256)
    delivery_facts_digest = column("deliveryFactsDigest", _SHA256)
    activated_at = column("activatedAt", _DT)

    manifest = op.create_table(
        "VolumeManifestHeader",
        Column("id", _ID, primary_key=True),
        Column("libraryId", _ID, nullable=False),
        Column("volumeId", _ID, nullable=False),
        Column("kind", _enum("manifestkind", "REQUIRED"), nullable=False),
        Column(
            "state",
            _enum(
                "requiredmanifeststate",
                "STAGING",
                "ACTIVE",
            ),
            nullable=False,
        ),
        Column("topologyUnitRevisionId", _ID, nullable=False),
        Column("processorVersion", String(64), nullable=False),
        Column("processingRevision", BigInteger, nullable=False),
        Column("topologyVersion", Integer, nullable=False),
        Column("readingMorphology", String(32), nullable=False),
        Column(
            "deliveryPolicy",
            _enum("requireddeliverypolicy", "ORIGINAL_SOURCE"),
            nullable=False,
        ),
        Column("deliveryPolicyVersion", Integer, nullable=False),
        Column("baseContentRevision", BigInteger, nullable=False),
        Column("baseRequiredManifestRevision", BigInteger, nullable=False),
        Column("publishedContentRevision", BigInteger),
        Column("publishedRequiredManifestRevision", BigInteger),
        Column("expectedEntryCount", Integer, nullable=False),
        Column("stagedEntryCount", Integer, nullable=False),
        Column("sourceBytesDigest", _SHA256, nullable=False),
        Column("contentFactsDigest", _SHA256, nullable=False),
        Column("deliveryFactsDigest", _SHA256, nullable=False),
        Column("activatedAt", _DT),
        Column(
            "createdAt",
            _DT,
            nullable=False,
            server_default=func.current_timestamp(),
        ),
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
        CheckConstraint(
            and_(
                processing_revision > 0,
                func.length(func.trim(processor_version)) > 0,
                topology_version > 0,
                delivery_policy_version > 0,
                base_content_revision >= 0,
                base_required_revision >= 0,
                or_(
                    and_(
                        base_content_revision == 0,
                        base_required_revision == 0,
                    ),
                    and_(
                        base_content_revision > 0,
                        base_required_revision > 0,
                    ),
                ),
                expected_entry_count.between(1, 10_000),
                staged_entry_count >= 0,
                staged_entry_count <= expected_entry_count,
            ),
            name="VolumeManifestHeader_bounds_ck",
        ),
        CheckConstraint(
            or_(
                and_(
                    published_content_revision.is_(None),
                    published_required_revision.is_(None),
                ),
                and_(
                    published_content_revision > 0,
                    published_required_revision > 0,
                    published_required_revision == base_required_revision + 1,
                    published_content_revision.in_(
                        (base_content_revision, base_content_revision + 1)
                    ),
                    or_(
                        base_content_revision > 0,
                        published_content_revision == 1,
                    ),
                ),
            ),
            name="VolumeManifestHeader_published_vector_ck",
        ),
        CheckConstraint(
            and_(
                func.length(source_bytes_digest) == 71,
                source_bytes_digest.regexp_match(_SHA256_PATTERN),
                func.length(content_facts_digest) == 71,
                content_facts_digest.regexp_match(_SHA256_PATTERN),
                func.length(delivery_facts_digest) == 71,
                delivery_facts_digest.regexp_match(_SHA256_PATTERN),
            ),
            name="VolumeManifestHeader_digest_shape_ck",
        ),
        CheckConstraint(
            or_(
                and_(
                    state == "STAGING",
                    published_content_revision.is_(None),
                    published_required_revision.is_(None),
                    activated_at.is_(None),
                ),
                and_(
                    state == "ACTIVE",
                    staged_entry_count == expected_entry_count,
                    published_content_revision.is_not(None),
                    published_required_revision.is_not(None),
                    activated_at.is_not(None),
                ),
            ),
            name="VolumeManifestHeader_state_shape_ck",
        ),
    )
    for index in (
        Index(
            "VolumeManifestHeader_one_active_idx",
            manifest.c.libraryId,
            manifest.c.volumeId,
            manifest.c.kind,
            unique=True,
            sqlite_where=manifest.c.state == "ACTIVE",
        ),
        Index(
            "VolumeManifestHeader_one_staging_idx",
            manifest.c.libraryId,
            manifest.c.volumeId,
            manifest.c.kind,
            unique=True,
            sqlite_where=manifest.c.state == "STAGING",
        ),
        Index(
            "VolumeManifestHeader_reader_idx",
            manifest.c.libraryId,
            manifest.c.volumeId,
            manifest.c.kind,
            manifest.c.state,
            manifest.c.id,
        ),
    ):
        index.create(bind=op.get_bind())

    source_fact_revision = column("sourceFactRevision", BigInteger)
    size_bytes = column("sizeBytes", BigInteger)
    asset_order = column("assetOrder", Integer)
    role = column("role", String(14))
    mime_type = column("mimeType", String(191))
    content_digest = column("contentDigest", _SHA256)
    op.create_table(
        "VolumeManifestEntry",
        Column("id", _ID, primary_key=True),
        Column("libraryId", _ID, nullable=False),
        Column("volumeId", _ID, nullable=False),
        Column("manifestId", _ID, nullable=False),
        Column("assetId", _ID, nullable=False),
        Column("sourceEntryId", _ID, nullable=False),
        Column("sourceFactRevision", BigInteger, nullable=False),
        Column(
            "role",
            _enum("assetrole", "PRIMARY", "AUDIO_TRACK", "READER_SIDECAR"),
            nullable=False,
        ),
        Column("sourceFormat", String(64), nullable=False),
        Column("mimeType", String(191), nullable=False),
        Column("sizeBytes", BigInteger, nullable=False),
        Column("contentDigest", _SHA256, nullable=False),
        Column("filesystemIdentity", String(191), nullable=False),
        Column("modifiedNs", BigInteger, nullable=False),
        Column("assetOrder", Integer, nullable=False),
        Column(
            "createdAt",
            _DT,
            nullable=False,
            server_default=func.current_timestamp(),
        ),
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
        CheckConstraint(
            and_(
                source_fact_revision > 0,
                size_bytes >= 0,
                asset_order.between(0, 9_999),
                role.in_(("PRIMARY", "AUDIO_TRACK")),
                mime_type.regexp_match(r"^[a-z0-9!#$&^_.+-]+/[a-z0-9!#$&^_.+-]+$"),
                func.length(content_digest) == 71,
                content_digest.regexp_match(_SHA256_PATTERN),
            ),
            name="VolumeManifestEntry_shape_ck",
        ),
    )


def _create_volume_processing_fact() -> None:
    processor_version = column("processorVersion", String(64))
    work_revision = column("workRevision", BigInteger)
    expected_content_revision = column("expectedContentRevision", BigInteger)
    expected_required_revision = column("expectedRequiredManifestRevision", BigInteger)
    input_fingerprint = column("inputFingerprint", _SHA256)
    state = column("state", String(7))
    failure_code = column("failureCode", String(96))
    lease_owner = column("leaseOwner", _ID)
    lease_expires_at = column("leaseExpiresAt", _DT)

    processing = op.create_table(
        "VolumeProcessingFact",
        Column("libraryId", _ID, primary_key=True),
        Column("volumeId", _ID, primary_key=True),
        Column(
            "processorKind",
            _enum(
                "contentprocessorkind",
                "REQUIRED_MANIFEST",
                "REQUIRED_OPENING",
            ),
            primary_key=True,
        ),
        Column("workRevision", BigInteger, nullable=False),
        Column("processorVersion", String(64), nullable=False),
        Column("activeTopologyRevisionId", _ID, nullable=False),
        Column("expectedContentRevision", BigInteger, nullable=False),
        Column("expectedRequiredManifestRevision", BigInteger, nullable=False),
        Column("inputFingerprint", _SHA256, nullable=False),
        Column("availableAt", _DT, nullable=False),
        Column(
            "state",
            _enum("processorstate", "PENDING", "RUNNING", "READY", "FAILED"),
            nullable=False,
        ),
        Column("failureCode", String(96)),
        Column("leaseOwner", _ID),
        Column("leaseExpiresAt", _DT),
        Column(
            "createdAt",
            _DT,
            nullable=False,
            server_default=func.current_timestamp(),
        ),
        Column(
            "updatedAt",
            _DT,
            nullable=False,
            server_default=func.current_timestamp(),
        ),
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
        CheckConstraint(
            and_(
                work_revision > 0,
                func.length(func.trim(processor_version)) > 0,
                expected_content_revision >= 0,
                expected_required_revision >= 0,
                func.length(input_fingerprint) == 71,
                input_fingerprint.regexp_match(_SHA256_PATTERN),
            ),
            name="VolumeProcessingFact_revision_vector_ck",
        ),
        CheckConstraint(
            or_(
                and_(
                    state == "PENDING",
                    lease_owner.is_(None),
                    lease_expires_at.is_(None),
                    failure_code.is_(None),
                ),
                and_(
                    state == "RUNNING",
                    lease_owner.is_not(None),
                    lease_expires_at.is_not(None),
                    failure_code.is_(None),
                ),
                and_(
                    state == "READY",
                    lease_owner.is_(None),
                    lease_expires_at.is_(None),
                    failure_code.is_(None),
                ),
                and_(
                    state == "FAILED",
                    lease_owner.is_(None),
                    lease_expires_at.is_(None),
                    failure_code.is_not(None),
                ),
            ),
            name="VolumeProcessingFact_state_shape_ck",
        ),
    )
    Index(
        "VolumeProcessingFact_claim_idx",
        processing.c.libraryId,
        processing.c.processorKind,
        processing.c.state,
        processing.c.availableAt,
        processing.c.volumeId,
    ).create(bind=op.get_bind())


def upgrade() -> None:
    """Apply current required-content processing schema."""

    _extend_library_volume()
    _create_content_topology_projection_state()
    _create_source_content_fact()
    _create_manifest_tables()
    _create_volume_processing_fact()


def downgrade() -> None:
    """Reject downgrade before touching the append-only current schema."""

    raise NotImplementedError(
        "current schema lineage is append-only; downgrade is unsupported"
    )
