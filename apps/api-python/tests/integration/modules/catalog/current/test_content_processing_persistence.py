from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import NoReturn

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.db.current.bootstrap import bootstrap_system
from app.db.current.engine import create_current_engine
from app.db.current.runner import upgrade_current_schema
from app.modules.auth.infrastructure.persistence.models import CurrentUser
from app.modules.catalog.application.content_dto import (
    FullScanContentOrigin,
    ObservedContentSource,
    RequiredManifestStageBatch,
    SourceDigestEvidence,
    SourceDigestPublishDisposition,
    SourceDigestPublishOutcome,
    VolumeProcessingWorkFence,
)
from app.modules.catalog.application.content_dto import (
    SourceContentFact as SourceContentFactDto,
)
from app.modules.catalog.application.content_ports import ContentConflict
from app.modules.catalog.application.scan_dto import ScanFence, StagingRevision
from app.modules.catalog.application.source_admission_ports import (
    SourceStatExpectation,
)
from app.modules.catalog.domain.content import (
    CanonicalRequiredManifestFacts,
    ContentProcessorKind,
    RequiredContentAsset,
    RequiredDeliveryPolicy,
    Sha256Digest,
    canonical_required_mime_type,
    required_manifest_revision_impact,
)
from app.modules.catalog.domain.content import (
    SourceContentState as DomainSourceContentState,
)
from app.modules.catalog.domain.model import (
    AdmissionKind,
    OrganizationMode,
    PathComparison,
    SidecarRole,
    SourceFormat,
    SourceKind,
)
from app.modules.catalog.domain.scan import (
    AssetRole as DomainAssetRole,
)
from app.modules.catalog.domain.scan import ReadingMorphology
from app.modules.catalog.infrastructure.persistence import (
    AssetRole,
    AssetValidationState,
    CatalogLibrary,
    ContentOriginKind,
    ContentTopologyProjectionState,
    LayoutState,
    LibraryControlState,
    LibraryHealth,
    LibraryScanRun,
    LibrarySourceEntry,
    LibraryVolume,
    LibraryWork,
    ManifestKind,
    ProcessorState,
    RequiredManifestState,
    RevisionState,
    ScanStage,
    ScanState,
    SlotState,
    SourceContentFact,
    SourceContentState,
    SourceEntryType,
    SqlAlchemyContentUowFactory,
    SqlAlchemyScanUowFactory,
    TopologyAssetMembership,
    TopologyUnit,
    TopologyUnitKind,
    TopologyUnitRevision,
    TopologyVolumeProjection,
    VolumeAsset,
    VolumeContentState,
    VolumeManifestEntry,
    VolumeManifestHeader,
    VolumeProcessingFact,
    WorkVersion,
    WritePolicy,
)
from app.modules.catalog.infrastructure.persistence import (
    ContentProcessorKind as StoredContentProcessorKind,
)
from app.modules.catalog.infrastructure.persistence import (
    RequiredDeliveryPolicy as StoredRequiredDeliveryPolicy,
)

_NOW = datetime(2026, 1, 2, 3, 4, tzinfo=UTC)
_OLD_DIGEST = Sha256Digest.from_bytes(b"old source bytes")
_NEW_DIGEST = Sha256Digest.from_bytes(b"new source bytes")


class _SqliteBusyError(Exception):
    sqlite_errorcode = 5


class _CleanupTrackingSession(Session):
    rollback_called = False
    close_called = False

    def rollback(self) -> None:
        _CleanupTrackingSession.rollback_called = True
        super().rollback()

    def close(self) -> None:
        _CleanupTrackingSession.close_called = True
        super().close()


class _BusyCommitTrackingSession(_CleanupTrackingSession):
    def commit(self) -> None:
        raise OperationalError(None, None, _SqliteBusyError("database is locked"))


def _raise_busy(
    _connection: object,
    _cursor: object,
    _statement: str,
    _parameters: object,
    _context: object,
    _executemany: bool,
) -> NoReturn:
    raise OperationalError(None, None, _SqliteBusyError("database is locked"))


def _file_id(source_id: str) -> int:
    return sum((index + 1) * ord(value) for index, value in enumerate(source_id)) + 1


@pytest.fixture
def persistence(tmp_path: Path):
    database_path = tmp_path / "content.sqlite3"
    upgrade_current_schema(database_path)
    engine = create_current_engine(database_path)
    bootstrap_system(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    try:
        yield engine, factory
    finally:
        engine.dispose()


def _canonical_facts(
    digest: Sha256Digest,
    *,
    asset_id: str = "asset",
    source_format: SourceFormat = SourceFormat.PDF,
    size_bytes: int = 128,
) -> CanonicalRequiredManifestFacts:
    return CanonicalRequiredManifestFacts(
        topology_version=1,
        reading_morphology=(
            ReadingMorphology.AUDIO
            if source_format is SourceFormat.MP3
            else ReadingMorphology.PDF
        ),
        delivery_policy=RequiredDeliveryPolicy.ORIGINAL_SOURCE,
        delivery_policy_version=1,
        assets=(
            RequiredContentAsset(
                asset_id=asset_id,
                role=(
                    DomainAssetRole.AUDIO_TRACK
                    if source_format is SourceFormat.MP3
                    else DomainAssetRole.PRIMARY
                ),
                source_format=source_format,
                size_bytes=size_bytes,
                content_digest=digest,
                order=0,
                mime_type=canonical_required_mime_type(source_format),
            ),
        ),
    )


def _library() -> CatalogLibrary:
    return CatalogLibrary(
        id="library",
        name="Library",
        root_path="/srv/library",
        root_path_key="/srv/library",
        organization_mode=OrganizationMode.FLAT,
        topology_version=1,
        path_comparison=PathComparison.SENSITIVE,
        write_policy=WritePolicy.READ_ONLY,
        control_state=LibraryControlState.ACTIVE,
        observed_health=LibraryHealth.UNKNOWN,
        config_revision=1,
        topology_writer_fence=1,
        next_scan_generation=2,
        last_successful_generation=1,
        last_successful_scan_at=_NOW,
    )


def _root() -> LibrarySourceEntry:
    return LibrarySourceEntry(
        id="root",
        library_id="library",
        parent_entry_id=None,
        local_name="$root",
        local_name_key="$root",
        entry_type=SourceEntryType.SYNTHETIC_ROOT,
        filesystem_identity="dev:root",
        size_bytes=None,
        modified_ns=None,
        last_seen_generation=1,
        absence_confirmed_at=None,
        children_presence_epoch=0,
        next_children_presence_epoch=0,
        observed_parent_presence_epoch=None,
        pending_observed_parent_presence_epoch=None,
        layout_state=LayoutState.PRESENT,
        slot_state=SlotState.ACTIVE,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _file(source_id: str, *, name: str | None = None) -> LibrarySourceEntry:
    local_name = name or f"{source_id}.pdf"
    return LibrarySourceEntry(
        id=source_id,
        library_id="library",
        parent_entry_id="root",
        local_name=local_name,
        local_name_key=local_name,
        entry_type=SourceEntryType.FILE,
        filesystem_identity=f"dev:{source_id}",
        size_bytes=128,
        modified_ns=10,
        last_seen_generation=1,
        absence_confirmed_at=None,
        children_presence_epoch=0,
        next_children_presence_epoch=0,
        observed_parent_presence_epoch=0,
        pending_observed_parent_presence_epoch=None,
        layout_state=LayoutState.PRESENT,
        slot_state=SlotState.ACTIVE,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _content_fact(
    source_id: str,
    *,
    digest: Sha256Digest | None,
    state: SourceContentState,
    input_revision: int = 1,
) -> SourceContentFact:
    return SourceContentFact(
        library_id="library",
        source_entry_id=source_id,
        input_revision=input_revision,
        work_revision=0,
        digest_input_revision=(input_revision if digest is not None else None),
        admission=AdmissionKind.PRIMARY.value,
        source_format=SourceFormat.PDF.value,
        filesystem_identity=f"dev:{source_id}",
        device_id=1,
        file_id=_file_id(source_id),
        size_bytes=128,
        modified_ns=10,
        policy_version=1,
        origin_kind=ContentOriginKind.FULL_SCAN,
        origin_id="seed-scan",
        origin_sequence=1,
        available_at=_NOW,
        state=state,
        content_digest=None if digest is None else digest.value,
        lease_owner=None,
        lease_expires_at=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _seed_single_volume(
    factory: sessionmaker[Session],
    *,
    volume_id: str = "volume",
    source_id: str = "source",
    current_digest: Sha256Digest | None = _NEW_DIGEST,
    initial_revisions: tuple[int, int] = (0, 0),
    required_manifest_source: Sha256Digest | None = None,
    required_membership: bool = True,
    create_processing: bool = True,
) -> CanonicalRequiredManifestFacts | None:
    facts = None if current_digest is None else _canonical_facts(current_digest)
    published_digest = required_manifest_source
    if initial_revisions != (0, 0) and published_digest is None:
        published_digest = current_digest
    with factory.begin() as session:
        session.add_all(
            (
                _library(),
                ContentTopologyProjectionState(
                    library_id="library",
                    requested_epoch=0,
                    claimed_epoch=0,
                    applied_epoch=0,
                    cursor_volume_id=None,
                    updated_at=_NOW,
                ),
                _root(),
                _file(source_id),
            )
        )
        session.add_all(
            (
                LibraryWork(id="work", library_id="library"),
                WorkVersion(id="version", library_id="library"),
                LibraryVolume(
                    id=volume_id,
                    library_id="library",
                    reading_morphology=ReadingMorphology.PDF.value,
                    content_state=VolumeContentState.PENDING,
                    content_revision=initial_revisions[0],
                    required_manifest_revision=initial_revisions[1],
                    optional_manifest_revision=7,
                    metadata_revision=11,
                    required_manifest_digest=(
                        None
                        if published_digest is None
                        else _canonical_facts(
                            published_digest
                        ).fingerprints.source_bytes_digest.value
                    ),
                    publication_fingerprint=None,
                    created_at=_NOW,
                    updated_at=_NOW,
                ),
                VolumeAsset(
                    id="asset",
                    library_id="library",
                    source_format=SourceFormat.PDF.value,
                    mime_type=(
                        canonical_required_mime_type(SourceFormat.PDF)
                        if initial_revisions != (0, 0)
                        else None
                    ),
                    size_bytes=(128 if initial_revisions != (0, 0) else None),
                    content_digest=(
                        None
                        if initial_revisions == (0, 0) or current_digest is None
                        else current_digest.value
                    ),
                    validation_state=(
                        AssetValidationState.READY
                        if initial_revisions != (0, 0)
                        else AssetValidationState.PENDING
                    ),
                    created_at=_NOW,
                    updated_at=_NOW,
                ),
            )
        )
        session.flush()
        unit = TopologyUnit(
            id="unit",
            library_id="library",
            unit_kind=TopologyUnitKind.SINGLE_FILE_VOLUME,
            work_owner_id=None,
            version_owner_id=None,
            volume_owner_id=volume_id,
            active_revision_id=None,
            created_at=_NOW,
        )
        session.add(unit)
        session.flush()
        session.add(
            TopologyUnitRevision(
                id="topology-revision",
                library_id="library",
                unit_id="unit",
                scan_run_id=None,
                reconcile_origin_id="seed-origin",
                unit_root_entry_id=source_id,
                revision=1,
                state=RevisionState.ACTIVE,
                created_at=_NOW,
            )
        )
        session.flush()
        session.add_all(
            (
                TopologyVolumeProjection(
                    id="volume-projection",
                    library_id="library",
                    unit_revision_id="topology-revision",
                    volume_id=volume_id,
                    version_id="version",
                    root_entry_id=source_id,
                    source_kind=SourceKind.SINGLE_FILE,
                    reading_morphology=ReadingMorphology.PDF.value,
                    structure_key="volume",
                    source_name="book.pdf",
                    sort_key="book.pdf",
                ),
                TopologyAssetMembership(
                    id="membership",
                    library_id="library",
                    unit_revision_id="topology-revision",
                    asset_id="asset",
                    volume_id=volume_id,
                    source_entry_id=source_id,
                    role=AssetRole.PRIMARY,
                    source_format=SourceFormat.PDF.value,
                    disc_number=None,
                    asset_order=0,
                    required_for_reading=required_membership,
                ),
            )
        )
        unit.active_revision_id = "topology-revision"
        if current_digest is not None:
            session.add(
                _content_fact(
                    source_id,
                    digest=current_digest,
                    state=SourceContentState.READY,
                    input_revision=2 if initial_revisions != (0, 0) else 1,
                )
            )
        if create_processing and facts is not None:
            session.add(
                VolumeProcessingFact(
                    library_id="library",
                    volume_id=volume_id,
                    processor_kind=StoredContentProcessorKind.REQUIRED_MANIFEST,
                    work_revision=2 if initial_revisions != (0, 0) else 1,
                    processor_version="required-manifest-v1",
                    active_topology_revision_id="topology-revision",
                    expected_content_revision=initial_revisions[0],
                    expected_required_manifest_revision=initial_revisions[1],
                    input_fingerprint=(facts.fingerprints.delivery_facts_digest.value),
                    available_at=_NOW,
                    state=ProcessorState.PENDING,
                    failure_code=None,
                    lease_owner=None,
                    lease_expires_at=None,
                    created_at=_NOW,
                    updated_at=_NOW,
                )
            )
    return facts


def _active_manifest(
    *,
    manifest_id: str,
    facts: CanonicalRequiredManifestFacts,
) -> tuple[VolumeManifestHeader, VolumeManifestEntry]:
    fingerprints = facts.fingerprints
    asset = facts.assets[0]
    return (
        VolumeManifestHeader(
            id=manifest_id,
            library_id="library",
            volume_id="volume",
            kind=ManifestKind.REQUIRED,
            state=RequiredManifestState.ACTIVE,
            topology_unit_revision_id="topology-revision",
            processor_version="required-manifest-v1",
            processing_revision=1,
            topology_version=1,
            reading_morphology=ReadingMorphology.PDF.value,
            delivery_policy=StoredRequiredDeliveryPolicy.ORIGINAL_SOURCE,
            delivery_policy_version=1,
            base_content_revision=0,
            base_required_manifest_revision=0,
            published_content_revision=1,
            published_required_manifest_revision=1,
            expected_entry_count=1,
            staged_entry_count=1,
            source_bytes_digest=fingerprints.source_bytes_digest.value,
            content_facts_digest=fingerprints.content_facts_digest.value,
            delivery_facts_digest=fingerprints.delivery_facts_digest.value,
            activated_at=_NOW,
            created_at=_NOW,
        ),
        VolumeManifestEntry(
            id=f"entry-{manifest_id}",
            library_id="library",
            volume_id="volume",
            manifest_id=manifest_id,
            asset_id=asset.asset_id,
            source_entry_id="source",
            source_fact_revision=1,
            role=AssetRole.PRIMARY,
            source_format=asset.source_format.value,
            mime_type=asset.mime_type,
            size_bytes=asset.size_bytes,
            content_digest=asset.content_digest.value,
            filesystem_identity="dev:source",
            modified_ns=10,
            asset_order=0,
            created_at=_NOW,
        ),
    )


def _claim_manifest(
    factory: sessionmaker[Session],
    *,
    owner: str = "worker",
):
    lease_expires_at = _NOW + timedelta(minutes=5)
    with SqlAlchemyContentUowFactory(factory)() as uow:
        claimed = uow.processing.claim_next(
            "library",
            ContentProcessorKind.REQUIRED_MANIFEST,
            owner_token=owner,
            now=_NOW,
            lease_expires_at=lease_expires_at,
            defer_until=_NOW + timedelta(minutes=1),
        )
        assert claimed.work is not None
        assert claimed.deferred_count == 0
        fence = claimed.work.fence()
        uow.commit()
    return fence


def test_content_uow_busy_enter_preserves_cause_and_cleans_session(persistence) -> None:
    engine, _factory = persistence
    tracking_factory = sessionmaker(
        engine,
        class_=_CleanupTrackingSession,
        expire_on_commit=False,
    )
    _CleanupTrackingSession.rollback_called = False
    _CleanupTrackingSession.close_called = False
    event.listen(engine, "before_cursor_execute", _raise_busy)
    try:
        with (
            pytest.raises(ContentConflict) as raised,
            SqlAlchemyContentUowFactory(tracking_factory)(),
        ):
            pytest.fail("busy writer gate must not enter the unit of work")
    finally:
        event.remove(engine, "before_cursor_execute", _raise_busy)

    assert isinstance(raised.value.__cause__, OperationalError)
    assert _CleanupTrackingSession.rollback_called
    assert _CleanupTrackingSession.close_called

    with tracking_factory() as session:
        assert session.scalar(select(func.count()).select_from(CatalogLibrary)) == 0


def test_content_uow_busy_commit_preserves_cause_and_rolls_back(persistence) -> None:
    engine, _factory = persistence
    tracking_factory = sessionmaker(
        engine,
        class_=_BusyCommitTrackingSession,
        expire_on_commit=False,
    )
    _CleanupTrackingSession.rollback_called = False
    _CleanupTrackingSession.close_called = False

    with (
        pytest.raises(ContentConflict) as raised,
        SqlAlchemyContentUowFactory(tracking_factory)() as uow,
    ):
        uow.commit()

    assert isinstance(raised.value.__cause__, OperationalError)
    assert _CleanupTrackingSession.rollback_called
    assert _CleanupTrackingSession.close_called


def test_first_required_manifest_activates_atomically(persistence) -> None:
    _engine, factory = persistence
    facts = _seed_single_volume(factory)
    assert facts is not None
    fence = _claim_manifest(factory)

    with SqlAlchemyContentUowFactory(factory)() as uow:
        candidate = uow.required_manifests.load_candidate(
            fence,
            manifest_id="manifest",
        )
        assert candidate is not None
        impact = required_manifest_revision_impact(
            None,
            candidate.facts.fingerprints,
            base_content_revision=0,
            base_required_manifest_revision=0,
        )
        staging = uow.required_manifests.begin_staging(
            fence,
            candidate,
            impact,
            created_at=_NOW,
        )
        assert staging is not None
        staging = uow.required_manifests.append_staging_batch(
            fence,
            staging,
            RequiredManifestStageBatch(0, candidate.facts.assets, True),
            staged_at=_NOW,
        )
        assert staging is not None
        activated = uow.required_manifests.activate_staging(
            fence,
            staging,
            impact,
            activated_at=_NOW,
        )
        assert activated is not None
        assert activated.published_revisions.content_revision == 1
        assert activated.published_revisions.required_manifest_revision == 1
        uow.commit()

    with factory() as session:
        volume = session.get(LibraryVolume, "volume")
        asset = session.get(VolumeAsset, "asset")
        assert volume is not None
        assert volume.content_revision == 1
        assert volume.required_manifest_revision == 1
        assert volume.optional_manifest_revision == 7
        assert volume.metadata_revision == 11
        assert volume.content_state is VolumeContentState.PENDING
        assert asset is not None
        assert asset.content_digest == _NEW_DIGEST.value
        assert asset.validation_state is AssetValidationState.READY
        assert (
            session.scalar(select(func.count()).select_from(VolumeManifestHeader)) == 1
        )
        assert (
            session.scalar(select(func.count()).select_from(VolumeManifestEntry)) == 1
        )


@pytest.mark.parametrize(
    ("active_id", "new_id"),
    (("z-active", "a-new"), ("a-active", "z-new")),
)
def test_manifest_replacement_is_safe_for_both_identifier_orders(
    persistence,
    active_id: str,
    new_id: str,
) -> None:
    _engine, factory = persistence
    current = _seed_single_volume(
        factory,
        current_digest=_NEW_DIGEST,
        initial_revisions=(1, 1),
        required_manifest_source=_OLD_DIGEST,
    )
    assert current is not None
    previous = _canonical_facts(_OLD_DIGEST)
    with factory.begin() as session:
        active, entry = _active_manifest(manifest_id=active_id, facts=previous)
        session.add(active)
        session.flush()
        session.add(entry)
        volume = session.get(LibraryVolume, "volume")
        assert volume is not None
        volume.required_manifest_digest = (
            previous.fingerprints.source_bytes_digest.value
        )

    fence = _claim_manifest(factory)
    with SqlAlchemyContentUowFactory(factory)() as uow:
        candidate = uow.required_manifests.load_candidate(fence, manifest_id=new_id)
        assert candidate is not None
        impact = required_manifest_revision_impact(
            previous.fingerprints,
            candidate.facts.fingerprints,
            base_content_revision=1,
            base_required_manifest_revision=1,
        )
        staging = uow.required_manifests.begin_staging(
            fence, candidate, impact, created_at=_NOW
        )
        assert staging is not None
        staging = uow.required_manifests.append_staging_batch(
            fence,
            staging,
            RequiredManifestStageBatch(0, candidate.facts.assets, True),
            staged_at=_NOW,
        )
        assert staging is not None
        activated = uow.required_manifests.activate_staging(
            fence, staging, impact, activated_at=_NOW
        )
        assert activated is not None
        assert activated.active_manifest_id == new_id
        uow.commit()

    with factory() as session:
        assert session.get(VolumeManifestHeader, active_id) is None
        current_header = session.get(VolumeManifestHeader, new_id)
        assert current_header is not None
        assert current_header.state is RequiredManifestState.ACTIVE
        volume = session.get(LibraryVolume, "volume")
        assert volume is not None
        assert (volume.content_revision, volume.required_manifest_revision) == (2, 2)


@pytest.mark.parametrize("complete", (False, True))
def test_reuse_active_cleans_stale_staging_and_rollback_restores_it(
    persistence,
    complete: bool,
) -> None:
    _engine, factory = persistence
    facts = _seed_single_volume(
        factory,
        current_digest=_OLD_DIGEST,
        initial_revisions=(1, 1),
    )
    assert facts is not None
    with factory.begin() as session:
        active, entry = _active_manifest(manifest_id="active", facts=facts)
        session.add(active)
        session.flush()
        session.add(entry)
        volume = session.get(LibraryVolume, "volume")
        assert volume is not None
        volume.required_manifest_digest = facts.fingerprints.source_bytes_digest.value

    fence = _claim_manifest(factory)
    with factory.begin() as session:
        stale = VolumeManifestHeader(
            id="stale",
            library_id="library",
            volume_id="volume",
            kind=ManifestKind.REQUIRED,
            state=RequiredManifestState.STAGING,
            topology_unit_revision_id="topology-revision",
            processor_version="stale-processor",
            processing_revision=99,
            topology_version=1,
            reading_morphology=ReadingMorphology.PDF.value,
            delivery_policy=StoredRequiredDeliveryPolicy.ORIGINAL_SOURCE,
            delivery_policy_version=1,
            base_content_revision=1,
            base_required_manifest_revision=1,
            published_content_revision=None,
            published_required_manifest_revision=None,
            expected_entry_count=1,
            staged_entry_count=int(complete),
            source_bytes_digest=facts.fingerprints.source_bytes_digest.value,
            content_facts_digest=facts.fingerprints.content_facts_digest.value,
            delivery_facts_digest=facts.fingerprints.delivery_facts_digest.value,
            activated_at=None,
            created_at=_NOW,
        )
        session.add(stale)
        session.flush()
        if complete:
            _, entry = _active_manifest(manifest_id="stale", facts=facts)
            entry.id = "entry-stale"
            session.add(entry)

    def retarget(*, commit: bool) -> None:
        with SqlAlchemyContentUowFactory(factory)() as uow:
            candidate = uow.required_manifests.load_candidate(
                fence, manifest_id="unused"
            )
            assert candidate is not None
            impact = required_manifest_revision_impact(
                facts.fingerprints,
                candidate.facts.fingerprints,
                base_content_revision=1,
                base_required_manifest_revision=1,
            )
            outcome = uow.required_manifests.retarget_active(
                fence,
                candidate,
                impact,
                retargeted_at=_NOW,
            )
            assert outcome is not None
            assert outcome.active_manifest_id == "active"
            if commit:
                uow.commit()

    retarget(commit=False)
    with factory() as session:
        assert session.get(VolumeManifestHeader, "stale") is not None
        processing = session.get(
            VolumeProcessingFact,
            ("library", "volume", StoredContentProcessorKind.REQUIRED_MANIFEST),
        )
        assert processing is not None and processing.state is ProcessorState.RUNNING

    retarget(commit=True)
    with factory() as session:
        assert session.get(VolumeManifestHeader, "stale") is None
        assert session.get(VolumeManifestHeader, "active") is not None
        assert (
            session.scalar(select(func.count()).select_from(VolumeManifestHeader)) == 1
        )
        assert (
            session.scalar(select(func.count()).select_from(VolumeManifestEntry)) == 1
        )


def test_retarget_waits_for_required_asset_projection_then_reopens_current_stat(
    persistence,
) -> None:
    _engine, factory = persistence
    facts = _seed_single_volume(
        factory,
        current_digest=_OLD_DIGEST,
        initial_revisions=(1, 1),
    )
    assert facts is not None
    fingerprint = Sha256Digest.from_bytes(b"old-publication")
    with factory.begin() as session:
        active, entry = _active_manifest(manifest_id="active", facts=facts)
        session.add(active)
        session.flush()
        session.add(entry)
        source = session.get(LibrarySourceEntry, "source")
        fact = session.get(SourceContentFact, ("library", "source"))
        volume = session.get(LibraryVolume, "volume")
        asset = session.get(VolumeAsset, "asset")
        assert source is not None and fact is not None
        assert volume is not None and asset is not None
        source.modified_ns = 20
        fact.modified_ns = 20
        volume.content_state = VolumeContentState.READY
        volume.publication_fingerprint = fingerprint.value
        asset.validation_state = AssetValidationState.PENDING
        session.add(
            VolumeProcessingFact(
                library_id="library",
                volume_id="volume",
                processor_kind=StoredContentProcessorKind.REQUIRED_OPENING,
                work_revision=5,
                processor_version="required-opening-v0",
                active_topology_revision_id="topology-revision",
                expected_content_revision=1,
                expected_required_manifest_revision=1,
                input_fingerprint=facts.fingerprints.content_facts_digest.value,
                available_at=_NOW,
                state=ProcessorState.READY,
                failure_code=None,
                lease_owner=None,
                lease_expires_at=None,
                created_at=_NOW,
                updated_at=_NOW,
            )
        )

    manifest_fence = _claim_manifest(factory)
    with SqlAlchemyContentUowFactory(factory)() as uow:
        candidate = uow.required_manifests.load_candidate(
            manifest_fence,
            manifest_id="unused",
        )
        assert candidate is not None
        impact = required_manifest_revision_impact(
            facts.fingerprints,
            candidate.facts.fingerprints,
            base_content_revision=1,
            base_required_manifest_revision=1,
        )
        reused = uow.required_manifests.retarget_active(
            manifest_fence,
            candidate,
            impact,
            retargeted_at=_NOW,
        )
        assert reused is None

    current = SourceContentFactDto(
        library_id="library",
        source_entry_id="source",
        input_revision=2,
        work_revision=0,
        admission=AdmissionKind.PRIMARY,
        source_format=SourceFormat.PDF,
        filesystem_identity="dev:source",
        expected_stat=SourceStatExpectation(1, _file_id("source"), 128, 20),
        policy_version=1,
        state=DomainSourceContentState.READY,
        content_digest=_OLD_DIGEST,
        digest_input_revision=2,
        last_origin=FullScanContentOrigin("seed-scan", 1),
        available_at=_NOW,
    )
    with SqlAlchemyContentUowFactory(factory)() as uow:
        scheduled = uow.processing.schedule_required_manifest_for_digest(
            SourceDigestPublishOutcome(
                SourceDigestPublishDisposition.READY_CHANGED,
                2,
                current,
            ),
            scheduled_at=_NOW,
        )
        assert scheduled.wake_required
        uow.commit()

    manifest_fence = _claim_manifest(factory)
    with SqlAlchemyContentUowFactory(factory)() as uow:
        candidate = uow.required_manifests.load_candidate(
            manifest_fence,
            manifest_id="unused",
        )
        assert candidate is not None
        impact = required_manifest_revision_impact(
            facts.fingerprints,
            candidate.facts.fingerprints,
            base_content_revision=1,
            base_required_manifest_revision=1,
        )
        reused = uow.required_manifests.retarget_active(
            manifest_fence,
            candidate,
            impact,
            retargeted_at=_NOW,
        )
        assert reused is not None
        scheduled = uow.processing.schedule_required_opening(
            manifest_fence,
            reused,
            topology_unit_revision_id="topology-revision",
            scheduled_at=_NOW,
        )
        assert scheduled is not None and scheduled.wake_required
        uow.commit()

    with factory() as session:
        asset = session.get(VolumeAsset, "asset")
        volume = session.get(LibraryVolume, "volume")
        opening = session.get(
            VolumeProcessingFact,
            ("library", "volume", StoredContentProcessorKind.REQUIRED_OPENING),
        )
        assert (
            asset is not None and asset.validation_state is AssetValidationState.READY
        )
        assert asset.content_digest == _OLD_DIGEST.value
        assert volume is not None and volume.content_state is VolumeContentState.PENDING
        assert opening is not None and opening.state is ProcessorState.PENDING
        assert opening.processor_version == "required-opening-v1"

    with SqlAlchemyContentUowFactory(factory)() as uow:
        claimed = uow.processing.claim_next(
            "library",
            ContentProcessorKind.REQUIRED_OPENING,
            owner_token="opening-worker",
            now=_NOW,
            lease_expires_at=_NOW + timedelta(minutes=5),
            defer_until=_NOW + timedelta(minutes=1),
        )
        assert claimed.work is not None
        request = uow.processing.load_required_opening_request(claimed.work.fence())
        assert request is not None
        assert request.sources[0].expected_stat.modified_ns == 20
        assert request.sources[0].content_digest == _OLD_DIGEST
        uow.commit()


def test_topology_pointer_invalidates_old_ready_manifest_until_bounded_retarget(
    persistence,
) -> None:
    _engine, factory = persistence
    facts = _seed_single_volume(
        factory,
        current_digest=_OLD_DIGEST,
        initial_revisions=(1, 1),
    )
    assert facts is not None
    old_fingerprint = Sha256Digest.from_bytes(b"old-opening")
    lease_expires_at = _NOW + timedelta(minutes=5)
    with factory.begin() as session:
        active, entry = _active_manifest(manifest_id="active", facts=facts)
        session.add(active)
        session.flush()
        session.add(entry)
        volume = session.get(LibraryVolume, "volume")
        unit = session.get(TopologyUnit, "unit")
        old_revision = session.get(TopologyUnitRevision, "topology-revision")
        state = session.get(ContentTopologyProjectionState, "library")
        assert volume is not None and unit is not None and old_revision is not None
        assert state is not None
        volume.content_state = VolumeContentState.READY
        volume.publication_fingerprint = old_fingerprint.value
        old_revision.state = RevisionState.SUPERSEDED
        session.flush()
        session.add(
            TopologyUnitRevision(
                id="topology-revision-2",
                library_id="library",
                unit_id="unit",
                scan_run_id=None,
                reconcile_origin_id="rename-origin",
                unit_root_entry_id="source",
                revision=2,
                state=RevisionState.ACTIVE,
                created_at=_NOW,
            )
        )
        session.flush()
        session.add_all(
            (
                TopologyVolumeProjection(
                    id="volume-projection-2",
                    library_id="library",
                    unit_revision_id="topology-revision-2",
                    volume_id="volume",
                    version_id="version",
                    root_entry_id="source",
                    source_kind=SourceKind.SINGLE_FILE,
                    reading_morphology=ReadingMorphology.PDF.value,
                    structure_key="volume",
                    source_name="renamed.pdf",
                    sort_key="renamed.pdf",
                ),
                TopologyAssetMembership(
                    id="membership-2",
                    library_id="library",
                    unit_revision_id="topology-revision-2",
                    asset_id="asset",
                    volume_id="volume",
                    source_entry_id="source",
                    role=AssetRole.PRIMARY,
                    source_format=SourceFormat.PDF.value,
                    disc_number=None,
                    asset_order=0,
                    required_for_reading=True,
                ),
            )
        )
        unit.active_revision_id = "topology-revision-2"
        state.requested_epoch = 1
        session.add(
            VolumeProcessingFact(
                library_id="library",
                volume_id="volume",
                processor_kind=StoredContentProcessorKind.REQUIRED_OPENING,
                work_revision=1,
                processor_version="required-opening-v1",
                active_topology_revision_id="topology-revision-2",
                expected_content_revision=1,
                expected_required_manifest_revision=1,
                input_fingerprint=facts.fingerprints.content_facts_digest.value,
                available_at=_NOW,
                state=ProcessorState.RUNNING,
                failure_code=None,
                lease_owner="old-opening",
                lease_expires_at=lease_expires_at,
                created_at=_NOW,
                updated_at=_NOW,
            )
        )

    stale_opening_fence = VolumeProcessingWorkFence(
        "library",
        "volume",
        ContentProcessorKind.REQUIRED_OPENING,
        1,
        "old-opening",
        lease_expires_at,
    )
    with SqlAlchemyContentUowFactory(factory)() as uow:
        assert uow.processing.load_required_opening_request(stale_opening_fence) is None

    with factory.begin() as session:
        stale_opening = session.get(
            VolumeProcessingFact,
            ("library", "volume", StoredContentProcessorKind.REQUIRED_OPENING),
        )
        assert stale_opening is not None
        session.delete(stale_opening)

    with SqlAlchemyContentUowFactory(factory)() as uow:
        projected = uow.topology_projection.project_next_batch(
            "library",
            limit=500,
            projected_at=_NOW,
        )
        assert projected.processed_volume_count == 1
        uow.commit()

    manifest_fence = _claim_manifest(factory)
    with SqlAlchemyContentUowFactory(factory)() as uow:
        candidate = uow.required_manifests.load_candidate(
            manifest_fence,
            manifest_id="unused",
        )
        assert candidate is not None
        impact = required_manifest_revision_impact(
            facts.fingerprints,
            candidate.facts.fingerprints,
            base_content_revision=1,
            base_required_manifest_revision=1,
        )
        reused = uow.required_manifests.retarget_active(
            manifest_fence,
            candidate,
            impact,
            retargeted_at=_NOW,
        )
        assert reused is not None
        assert reused.published_revisions.content_revision == 1
        assert reused.published_revisions.required_manifest_revision == 1
        scheduled = uow.processing.schedule_required_opening(
            manifest_fence,
            reused,
            topology_unit_revision_id="topology-revision-2",
            scheduled_at=_NOW,
        )
        assert scheduled is not None
        uow.commit()

    with factory() as session:
        active = session.get(VolumeManifestHeader, "active")
        volume = session.get(LibraryVolume, "volume")
        assert active is not None and volume is not None
        assert active.topology_unit_revision_id == "topology-revision-2"
        assert (volume.content_revision, volume.required_manifest_revision) == (1, 1)

    with SqlAlchemyContentUowFactory(factory)() as uow:
        claimed = uow.processing.claim_next(
            "library",
            ContentProcessorKind.REQUIRED_OPENING,
            owner_token="new-opening",
            now=_NOW,
            lease_expires_at=lease_expires_at,
            defer_until=_NOW + timedelta(minutes=1),
        )
        assert claimed.work is not None
        request = uow.processing.load_required_opening_request(claimed.work.fence())
        assert request is not None
        assert request.topology_unit_revision_id == "topology-revision-2"
        uow.commit()


def test_source_claim_defers_one_hundred_blocked_rows_then_claims_ready_row(
    persistence,
) -> None:
    _engine, factory = persistence
    _seed_single_volume(
        factory,
        volume_id="z-volume",
        source_id="z-source",
        current_digest=None,
        create_processing=False,
    )
    with factory.begin() as session:
        session.add(
            _content_fact(
                "z-source",
                digest=None,
                state=SourceContentState.PENDING,
            )
        )
        for index in range(100):
            source_id = f"a{index:03d}"
            session.add(_file(source_id))
            session.add(
                _content_fact(
                    source_id,
                    digest=None,
                    state=SourceContentState.PENDING,
                )
            )

    deferred_until = _NOW + timedelta(minutes=2)
    with SqlAlchemyContentUowFactory(factory)() as uow:
        outcome = uow.source_contents.claim_next_digest(
            "library",
            owner_token="digest-worker",
            now=_NOW,
            lease_expires_at=_NOW + timedelta(minutes=5),
            defer_until=deferred_until,
        )
        assert outcome.deferred_count == 100
        assert outcome.work is not None
        assert outcome.work.fence.source_entry_id == "z-source"
        uow.commit()

    with factory() as session:
        deferred = session.get(SourceContentFact, ("library", "a000"))
        claimed = session.get(SourceContentFact, ("library", "z-source"))
        assert deferred is not None and deferred.available_at == deferred_until.replace(
            tzinfo=None
        )
        assert claimed is not None and claimed.state is SourceContentState.RUNNING


def test_processing_claim_defers_one_hundred_blocked_rows_then_claims_ready_row(
    persistence,
) -> None:
    _engine, factory = persistence
    facts = _seed_single_volume(factory, volume_id="z-volume")
    assert facts is not None
    with factory.begin() as session:
        for index in range(100):
            volume_id = f"a{index:03d}"
            session.add(
                LibraryVolume(
                    id=volume_id,
                    library_id="library",
                    reading_morphology=ReadingMorphology.PDF.value,
                    content_state=VolumeContentState.PENDING,
                    content_revision=0,
                    required_manifest_revision=0,
                    optional_manifest_revision=0,
                    metadata_revision=0,
                    required_manifest_digest=None,
                    publication_fingerprint=None,
                    created_at=_NOW,
                    updated_at=_NOW,
                )
            )
            session.add(
                VolumeProcessingFact(
                    library_id="library",
                    volume_id=volume_id,
                    processor_kind=StoredContentProcessorKind.REQUIRED_MANIFEST,
                    work_revision=1,
                    processor_version="required-manifest-v1",
                    active_topology_revision_id="topology-revision",
                    expected_content_revision=0,
                    expected_required_manifest_revision=0,
                    input_fingerprint=facts.fingerprints.delivery_facts_digest.value,
                    available_at=_NOW,
                    state=ProcessorState.PENDING,
                    failure_code=None,
                    lease_owner=None,
                    lease_expires_at=None,
                    created_at=_NOW,
                    updated_at=_NOW,
                )
            )

    deferred_until = _NOW + timedelta(minutes=2)
    with SqlAlchemyContentUowFactory(factory)() as uow:
        outcome = uow.processing.claim_next(
            "library",
            ContentProcessorKind.REQUIRED_MANIFEST,
            owner_token="manifest-worker",
            now=_NOW,
            lease_expires_at=_NOW + timedelta(minutes=5),
            defer_until=deferred_until,
        )
        assert outcome.deferred_count == 100
        assert outcome.work is not None
        assert outcome.work.volume_id == "z-volume"
        uow.commit()


def test_optional_membership_does_not_schedule_required_processing(persistence) -> None:
    _engine, factory = persistence
    _seed_single_volume(
        factory,
        current_digest=_NEW_DIGEST,
        required_membership=False,
        create_processing=False,
    )
    current = SourceContentFactDto(
        library_id="library",
        source_entry_id="source",
        input_revision=1,
        work_revision=0,
        admission=AdmissionKind.PRIMARY,
        source_format=SourceFormat.PDF,
        filesystem_identity="dev:source",
        expected_stat=SourceStatExpectation(1, _file_id("source"), 128, 10),
        policy_version=1,
        state=DomainSourceContentState.READY,
        content_digest=_NEW_DIGEST,
        digest_input_revision=1,
        last_origin=FullScanContentOrigin("seed-scan", 1),
        available_at=_NOW,
    )
    published = SourceDigestPublishOutcome(
        SourceDigestPublishDisposition.READY_CHANGED,
        1,
        current,
    )
    with SqlAlchemyContentUowFactory(factory)() as uow:
        scheduled = uow.processing.schedule_required_manifest_for_digest(
            published,
            scheduled_at=_NOW,
        )
        assert not scheduled.wake_required
        assert scheduled.affected_volume_count == 0
        uow.commit()

    with factory() as session:
        assert (
            session.scalar(select(func.count()).select_from(VolumeProcessingFact)) == 0
        )
        volume = session.get(LibraryVolume, "volume")
        asset = session.get(VolumeAsset, "asset")
        assert volume is not None and volume.content_state is VolumeContentState.PENDING
        assert (
            asset is not None and asset.validation_state is AssetValidationState.PENDING
        )


def _insert_running_scan(factory: sessionmaker[Session]) -> ScanFence:
    lease_expires_at = _NOW + timedelta(minutes=10)
    with factory.begin() as session:
        session.add(
            LibraryScanRun(
                id="scan",
                library_id="library",
                generation=1,
                config_revision=1,
                mode_snapshot=OrganizationMode.FLAT,
                root_path_snapshot="/srv/library",
                path_comparison_snapshot=PathComparison.SENSITIVE,
                topology_version_snapshot=1,
                watcher_sequence_watermark=0,
                root_identity_snapshot="dev:root",
                topology_writer_fence=1,
                state=ScanState.RUNNING,
                failure_code=None,
                stage=ScanStage.DISCOVER,
                lease_owner="scan-worker",
                lease_expires_at=lease_expires_at,
                heartbeat_at=_NOW,
                discovered_count=0,
                diagnostic_count=0,
                created_by_user_id=None,
                started_at=_NOW,
                finished_at=None,
                created_at=_NOW,
            )
        )
    return ScanFence(
        library_id="library",
        scan_id="scan",
        generation=1,
        config_revision=1,
        organization_mode=OrganizationMode.FLAT,
        topology_version=1,
        path_comparison=PathComparison.SENSITIVE,
        root_path_snapshot="/srv/library",
        root_identity="dev:root",
        topology_writer_fence=1,
        lease_owner="scan-worker",
    )


def _observed_content(
    admission: AdmissionKind,
    *,
    source_format: SourceFormat | None,
    sidecar_role: SidecarRole | None,
) -> ObservedContentSource:
    return ObservedContentSource(
        source_entry_id="source",
        relative_path=("source.pdf",),
        filesystem_identity="dev:source",
        expected_stat=SourceStatExpectation(1, _file_id("source"), 128, 10),
        admission=admission,
        source_format=source_format,
        sidecar_role=sidecar_role,
        policy_version=1,
        origin=FullScanContentOrigin("scan", 1),
    )


def test_observation_skips_first_ineligible_and_preserves_monotonic_reentry(
    persistence,
) -> None:
    _engine, factory = persistence
    _seed_single_volume(
        factory,
        current_digest=None,
        create_processing=False,
    )
    fence = _insert_running_scan(factory)

    with SqlAlchemyScanUowFactory(factory)() as uow:
        first_sidecar = uow.content_observations.observe_sources(
            fence,
            (
                _observed_content(
                    AdmissionKind.SIDECAR,
                    source_format=None,
                    sidecar_role=SidecarRole.OPF,
                ),
            ),
            observed_at=_NOW,
        )
        assert first_sidecar.facts == ()
        assert first_sidecar.advanced_required_count == 0
        uow.commit()

    with factory() as session:
        assert session.get(SourceContentFact, ("library", "source")) is None

    with SqlAlchemyScanUowFactory(factory)() as uow:
        required = uow.content_observations.observe_sources(
            fence,
            (
                _observed_content(
                    AdmissionKind.PRIMARY,
                    source_format=SourceFormat.PDF,
                    sidecar_role=None,
                ),
            ),
            observed_at=_NOW,
        )
        assert required.advanced_required_count == 1
        assert required.facts[0].input_revision == 1
        uow.commit()

    with SqlAlchemyScanUowFactory(factory)() as uow:
        ineligible = uow.content_observations.observe_sources(
            fence,
            (
                _observed_content(
                    AdmissionKind.UNSUPPORTED,
                    source_format=None,
                    sidecar_role=None,
                ),
            ),
            observed_at=_NOW,
        )
        assert ineligible.facts[0].input_revision == 2
        assert ineligible.facts[0].state is DomainSourceContentState.INELIGIBLE
        uow.commit()

    with SqlAlchemyScanUowFactory(factory)() as uow:
        reentered = uow.content_observations.observe_sources(
            fence,
            (
                _observed_content(
                    AdmissionKind.PRIMARY,
                    source_format=SourceFormat.PDF,
                    sidecar_role=None,
                ),
            ),
            observed_at=_NOW,
        )
        assert reentered.facts[0].input_revision == 3
        assert reentered.facts[0].state is DomainSourceContentState.PENDING
        assert reentered.advanced_required_count == 1
        uow.commit()


def test_same_stat_new_digest_advances_revision_before_scheduling_projection(
    persistence,
) -> None:
    _engine, factory = persistence
    _seed_single_volume(
        factory,
        current_digest=_OLD_DIGEST,
        create_processing=False,
    )
    with factory.begin() as session:
        fact = session.get(SourceContentFact, ("library", "source"))
        assert fact is not None
        fact.state = SourceContentState.PENDING
        fact.available_at = _NOW

    with SqlAlchemyContentUowFactory(factory)() as uow:
        claimed = uow.source_contents.claim_next_digest(
            "library",
            owner_token="digest-worker",
            now=_NOW,
            lease_expires_at=_NOW + timedelta(minutes=5),
            defer_until=_NOW + timedelta(minutes=1),
        )
        assert claimed.work is not None
        old_fence = claimed.work.fence
        published = uow.source_contents.publish_digest(
            old_fence,
            SourceDigestEvidence(
                source_entry_id="source",
                input_revision=1,
                observed_stat=claimed.work.request.expected_stat,
                bytes_hashed=128,
                content_digest=_NEW_DIGEST,
            ),
            published_at=_NOW,
        )
        assert published is not None
        assert (
            published.disposition
            is SourceDigestPublishDisposition.INPUT_REVISION_ADVANCED
        )
        assert published.current.input_revision == 2
        assert published.current.digest_input_revision == 2
        uow.commit()

    with factory() as session:
        assert (
            session.scalar(select(func.count()).select_from(VolumeProcessingFact)) == 0
        )
        asset = session.get(VolumeAsset, "asset")
        assert asset is not None and asset.content_digest is None

    with SqlAlchemyContentUowFactory(factory)() as uow:
        scheduled = uow.processing.schedule_required_manifest_for_digest(
            published,
            scheduled_at=_NOW,
        )
        assert scheduled.affected_volume_count == 1
        assert (
            uow.source_contents.publish_digest(
                old_fence,
                SourceDigestEvidence(
                    source_entry_id="source",
                    input_revision=1,
                    observed_stat=SourceStatExpectation(
                        1,
                        _file_id("source"),
                        128,
                        10,
                    ),
                    bytes_hashed=128,
                    content_digest=_OLD_DIGEST,
                ),
                published_at=_NOW,
            )
            is None
        )
        uow.commit()

    with factory() as session:
        assert (
            session.scalar(select(func.count()).select_from(VolumeProcessingFact)) == 1
        )
        asset = session.get(VolumeAsset, "asset")
        assert asset is not None and asset.content_digest == _NEW_DIGEST.value


def test_exact_pending_manifest_wake_moves_deferred_work_forward(persistence) -> None:
    _engine, factory = persistence
    _seed_single_volume(
        factory,
        current_digest=_NEW_DIGEST,
        create_processing=False,
    )
    current = SourceContentFactDto(
        library_id="library",
        source_entry_id="source",
        input_revision=1,
        work_revision=0,
        admission=AdmissionKind.PRIMARY,
        source_format=SourceFormat.PDF,
        filesystem_identity="dev:source",
        expected_stat=SourceStatExpectation(1, _file_id("source"), 128, 10),
        policy_version=1,
        state=DomainSourceContentState.READY,
        content_digest=_NEW_DIGEST,
        digest_input_revision=1,
        last_origin=FullScanContentOrigin("seed-scan", 1),
        available_at=_NOW,
    )
    published = SourceDigestPublishOutcome(
        SourceDigestPublishDisposition.READY_CHANGED,
        1,
        current,
    )
    with SqlAlchemyContentUowFactory(factory)() as uow:
        assert uow.processing.schedule_required_manifest_for_digest(
            published,
            scheduled_at=_NOW,
        ).wake_required
        uow.commit()

    future = _NOW + timedelta(seconds=30)
    with factory.begin() as session:
        processing = session.get(
            VolumeProcessingFact,
            ("library", "volume", StoredContentProcessorKind.REQUIRED_MANIFEST),
        )
        assert processing is not None
        processing.available_at = future

    awakened_at = _NOW + timedelta(seconds=1)
    with SqlAlchemyContentUowFactory(factory)() as uow:
        assert uow.processing.schedule_required_manifest_for_digest(
            published,
            scheduled_at=awakened_at,
        ).wake_required
        uow.commit()

    with factory() as session:
        processing = session.get(
            VolumeProcessingFact,
            ("library", "volume", StoredContentProcessorKind.REQUIRED_MANIFEST),
        )
        assert processing is not None
        assert processing.available_at == awakened_at.replace(tzinfo=None)


def _seed_large_topology_activation(
    factory: sessionmaker[Session],
    *,
    volume_count: int,
) -> tuple[ScanFence, tuple[StagingRevision, ...]]:
    lease_expires_at = _NOW + timedelta(minutes=10)
    with factory.begin() as session:
        session.add_all(
            (
                _library(),
                ContentTopologyProjectionState(
                    library_id="library",
                    requested_epoch=0,
                    claimed_epoch=0,
                    applied_epoch=0,
                    cursor_volume_id=None,
                    updated_at=_NOW,
                ),
                _root(),
                WorkVersion(id="version", library_id="library"),
                CurrentUser(id="admin", display_name="Admin", role="admin"),
            )
        )
        session.flush()
        session.add(
            LibraryScanRun(
                id="scan",
                library_id="library",
                generation=1,
                config_revision=1,
                mode_snapshot=OrganizationMode.FLAT,
                root_path_snapshot="/srv/library",
                path_comparison_snapshot=PathComparison.SENSITIVE,
                topology_version_snapshot=1,
                watcher_sequence_watermark=0,
                root_identity_snapshot="dev:root",
                topology_writer_fence=1,
                state=ScanState.RUNNING,
                failure_code=None,
                stage=ScanStage.RECONCILE,
                lease_owner="scan-worker",
                lease_expires_at=lease_expires_at,
                heartbeat_at=_NOW,
                discovered_count=0,
                diagnostic_count=0,
                created_by_user_id=None,
                started_at=_NOW,
                finished_at=None,
                created_at=_NOW,
            )
        )
        session.flush()
        for start in range(0, volume_count, 500):
            stop = min(start + 500, volume_count)
            volumes = [
                LibraryVolume(
                    id=f"volume-{index:05d}",
                    library_id="library",
                    reading_morphology=ReadingMorphology.PDF.value,
                    content_state=VolumeContentState.PENDING,
                    content_revision=0,
                    required_manifest_revision=0,
                    optional_manifest_revision=0,
                    metadata_revision=0,
                    required_manifest_digest=None,
                    publication_fingerprint=None,
                    created_at=_NOW,
                    updated_at=_NOW,
                )
                for index in range(start, stop)
            ]
            assets = [
                VolumeAsset(
                    id=f"asset-{index:05d}",
                    library_id="library",
                    source_format=SourceFormat.PDF.value,
                    mime_type="application/pdf",
                    size_bytes=128,
                    content_digest=_OLD_DIGEST.value,
                    validation_state=AssetValidationState.READY,
                    created_at=_NOW,
                    updated_at=_NOW,
                )
                for index in range(start, stop)
            ]
            session.add_all((*volumes, *assets))
            session.flush()
            units = [
                TopologyUnit(
                    id=f"unit-{index:05d}",
                    library_id="library",
                    unit_kind=TopologyUnitKind.SINGLE_FILE_VOLUME,
                    work_owner_id=None,
                    version_owner_id=None,
                    volume_owner_id=f"volume-{index:05d}",
                    active_revision_id=None,
                    created_at=_NOW,
                )
                for index in range(start, stop)
            ]
            session.add_all(units)
            session.flush()
            session.add_all(
                TopologyUnitRevision(
                    id=f"revision-{index:05d}",
                    library_id="library",
                    unit_id=f"unit-{index:05d}",
                    scan_run_id="scan",
                    reconcile_origin_id=None,
                    unit_root_entry_id="root",
                    revision=1,
                    state=RevisionState.ACTIVE,
                    created_at=_NOW,
                )
                for index in range(start, stop)
            )
            session.flush()
            projections: list[object] = []
            for index in range(start, stop):
                projections.extend(
                    (
                        TopologyVolumeProjection(
                            id=f"projection-{index:05d}",
                            library_id="library",
                            unit_revision_id=f"revision-{index:05d}",
                            volume_id=f"volume-{index:05d}",
                            version_id="version",
                            root_entry_id="root",
                            source_kind=SourceKind.SINGLE_FILE,
                            reading_morphology=ReadingMorphology.PDF.value,
                            structure_key=f"volume-{index:05d}",
                            source_name=f"book-{index:05d}.pdf",
                            sort_key=f"book-{index:05d}.pdf",
                        ),
                        TopologyAssetMembership(
                            id=f"membership-{index:05d}",
                            library_id="library",
                            unit_revision_id=f"revision-{index:05d}",
                            asset_id=f"asset-{index:05d}",
                            volume_id=f"volume-{index:05d}",
                            source_entry_id="root",
                            role=AssetRole.PRIMARY,
                            source_format=SourceFormat.PDF.value,
                            disc_number=None,
                            asset_order=0,
                            required_for_reading=True,
                        ),
                    )
                )
            session.add_all(projections)
            session.flush()
            for index, unit in zip(range(start, stop), units, strict=True):
                unit.active_revision_id = f"revision-{index:05d}"
            session.flush()
    fence = ScanFence(
        library_id="library",
        scan_id="scan",
        generation=1,
        config_revision=1,
        organization_mode=OrganizationMode.FLAT,
        topology_version=1,
        path_comparison=PathComparison.SENSITIVE,
        root_path_snapshot="/srv/library",
        root_identity="dev:root",
        topology_writer_fence=1,
        lease_owner="scan-worker",
    )
    staging = tuple(
        StagingRevision(
            revision_id=f"revision-{index:05d}",
            unit_id=f"unit-{index:05d}",
            expected_active_revision_id=None,
            expected_row_count=1,
            staged_row_count=1,
        )
        for index in range(volume_count)
    )
    return fence, staging


def test_ten_thousand_volume_topology_activation_is_statement_bounded(
    persistence,
) -> None:
    engine, factory = persistence
    fence, staging = _seed_large_topology_activation(factory, volume_count=10_000)
    statements: list[str] = []

    def capture_statement(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture_statement)
    try:
        with SqlAlchemyScanUowFactory(factory)() as uow:
            outcome = uow.content_topology.record_topology_activation(
                fence,
                staging,
                activated_at=_NOW,
            )
            assert outcome.state.requested_epoch == 1
            assert outcome.wake_required
            uow.commit()
    finally:
        event.remove(engine, "before_cursor_execute", capture_statement)

    assert len(statements) < 100
    assert not any('"LibraryVolume"' in statement for statement in statements)
    assert not any('"VolumeProcessingFact"' in statement for statement in statements)
    with factory() as session:
        state = session.get(ContentTopologyProjectionState, "library")
        assert state is not None
        assert (
            state.requested_epoch,
            state.claimed_epoch,
            state.applied_epoch,
            state.cursor_volume_id,
        ) == (1, 0, 0, None)
        assert (
            session.scalar(select(func.count()).select_from(VolumeProcessingFact)) == 0
        )


@pytest.mark.parametrize("volume_count", (499, 500, 501))
def test_topology_projection_batches_use_a_stable_five_hundred_volume_keyset(
    persistence,
    volume_count: int,
) -> None:
    _engine, factory = persistence
    fence, staging = _seed_large_topology_activation(
        factory,
        volume_count=volume_count,
    )
    with SqlAlchemyScanUowFactory(factory)() as uow:
        uow.content_topology.record_topology_activation(
            fence,
            staging,
            activated_at=_NOW,
        )
        uow.commit()

    with SqlAlchemyContentUowFactory(factory)() as uow:
        first = uow.topology_projection.project_next_batch(
            "library",
            limit=500,
            projected_at=_NOW,
        )
        assert first.projection_performed
        assert first.processed_volume_count == min(volume_count, 500)
        assert first.work_remaining == (volume_count == 501)
        if volume_count == 501:
            assert first.state.cursor_volume_id == "volume-00499"
        else:
            assert first.state.cursor_volume_id is None
        uow.commit()

    with factory() as session:
        assert session.scalar(
            select(func.count()).select_from(VolumeProcessingFact)
        ) == min(volume_count, 500)

    if volume_count == 501:
        with SqlAlchemyContentUowFactory(factory)() as uow:
            second = uow.topology_projection.project_next_batch(
                "library",
                limit=500,
                projected_at=_NOW + timedelta(seconds=1),
            )
            assert second.projection_performed
            assert second.processed_volume_count == 1
            assert not second.work_remaining
            uow.commit()

    with factory() as session:
        state = session.get(ContentTopologyProjectionState, "library")
        assert state is not None
        assert (
            state.requested_epoch,
            state.claimed_epoch,
            state.applied_epoch,
            state.cursor_volume_id,
        ) == (1, 1, 1, None)
        assert (
            session.scalar(select(func.count()).select_from(VolumeProcessingFact))
            == volume_count
        )


def test_projection_batch_rollback_retries_the_same_cursor_window(persistence) -> None:
    _engine, factory = persistence
    fence, staging = _seed_large_topology_activation(factory, volume_count=501)
    with SqlAlchemyScanUowFactory(factory)() as uow:
        uow.content_topology.record_topology_activation(
            fence,
            staging,
            activated_at=_NOW,
        )
        uow.commit()

    with SqlAlchemyContentUowFactory(factory)() as uow:
        rolled_back = uow.topology_projection.project_next_batch(
            "library",
            limit=500,
            projected_at=_NOW,
        )
        assert rolled_back.processed_volume_count == 500

    with factory() as session:
        state = session.get(ContentTopologyProjectionState, "library")
        assert state is not None
        assert (
            state.requested_epoch,
            state.claimed_epoch,
            state.applied_epoch,
            state.cursor_volume_id,
        ) == (1, 0, 0, None)
        assert (
            session.scalar(select(func.count()).select_from(VolumeProcessingFact)) == 0
        )

    with SqlAlchemyContentUowFactory(factory)() as uow:
        retried = uow.topology_projection.project_next_batch(
            "library",
            limit=500,
            projected_at=_NOW + timedelta(seconds=1),
        )
        assert retried.processed_volume_count == 500
        assert retried.state.cursor_volume_id == "volume-00499"
        uow.commit()


def test_projection_successor_epoch_is_replayed_from_the_beginning(persistence) -> None:
    _engine, factory = persistence
    fence, staging = _seed_large_topology_activation(factory, volume_count=501)
    with SqlAlchemyScanUowFactory(factory)() as uow:
        uow.content_topology.record_topology_activation(
            fence,
            staging,
            activated_at=_NOW,
        )
        uow.commit()
    with SqlAlchemyContentUowFactory(factory)() as uow:
        first = uow.topology_projection.project_next_batch(
            "library",
            limit=500,
            projected_at=_NOW,
        )
        assert first.state.cursor_volume_id == "volume-00499"
        uow.commit()

    with SqlAlchemyScanUowFactory(factory)() as uow:
        successor = uow.content_topology.record_topology_activation(
            fence,
            staging,
            activated_at=_NOW + timedelta(seconds=1),
        )
        assert successor.state.requested_epoch == 2
        assert not successor.wake_required
        uow.commit()

    with SqlAlchemyContentUowFactory(factory)() as uow:
        old_tail = uow.topology_projection.project_next_batch(
            "library",
            limit=500,
            projected_at=_NOW + timedelta(seconds=2),
        )
        assert old_tail.processed_volume_count == 1
        assert old_tail.work_remaining
        assert (
            old_tail.state.requested_epoch,
            old_tail.state.claimed_epoch,
            old_tail.state.applied_epoch,
            old_tail.state.cursor_volume_id,
        ) == (2, 2, 1, None)
        uow.commit()

    with SqlAlchemyContentUowFactory(factory)() as uow:
        replayed_tail = uow.topology_projection.project_next_batch(
            "library",
            limit=500,
            projected_at=_NOW + timedelta(seconds=3),
        )
        assert replayed_tail.processed_volume_count == 0
        assert not replayed_tail.work_remaining
        assert replayed_tail.state.applied_epoch == 2
        uow.commit()


def test_projection_claims_latest_epoch_when_successor_precedes_the_sweep(
    persistence,
) -> None:
    _engine, factory = persistence
    fence, staging = _seed_large_topology_activation(factory, volume_count=1)
    with SqlAlchemyScanUowFactory(factory)() as uow:
        first = uow.content_topology.record_topology_activation(
            fence,
            staging,
            activated_at=_NOW,
        )
        successor = uow.content_topology.record_topology_activation(
            fence,
            staging,
            activated_at=_NOW + timedelta(seconds=1),
        )
        assert first.wake_required
        assert not successor.wake_required
        assert successor.state.requested_epoch == 2
        uow.commit()

    with SqlAlchemyContentUowFactory(factory)() as uow:
        projected = uow.topology_projection.project_next_batch(
            "library",
            limit=500,
            projected_at=_NOW + timedelta(seconds=2),
        )
        assert projected.processed_volume_count == 1
        assert not projected.work_remaining
        assert (
            projected.state.requested_epoch,
            projected.state.claimed_epoch,
            projected.state.applied_epoch,
        ) == (2, 2, 2)
        uow.commit()


def test_projection_follows_multi_volume_audiobook_work_revision(persistence) -> None:
    _engine, factory = persistence
    _seed_single_volume(factory, current_digest=None, create_processing=False)
    with factory.begin() as session:
        unit = session.get(TopologyUnit, "unit")
        state = session.get(ContentTopologyProjectionState, "library")
        assert unit is not None and state is not None
        unit.unit_kind = TopologyUnitKind.AUDIOBOOK_WORK
        unit.work_owner_id = "work"
        unit.volume_owner_id = None
        session.add(
            LibraryVolume(
                id="volume-2",
                library_id="library",
                reading_morphology=ReadingMorphology.AUDIO.value,
                content_state=VolumeContentState.PENDING,
                content_revision=0,
                required_manifest_revision=0,
                optional_manifest_revision=0,
                metadata_revision=0,
                required_manifest_digest=None,
                publication_fingerprint=None,
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        session.flush()
        session.add(
            TopologyVolumeProjection(
                id="volume-projection-2",
                library_id="library",
                unit_revision_id="topology-revision",
                volume_id="volume-2",
                version_id="version",
                root_entry_id="source",
                source_kind=SourceKind.MULTI_ASSET_AUDIO,
                reading_morphology=ReadingMorphology.AUDIO.value,
                structure_key="volume-2",
                source_name="disc-2",
                sort_key="disc-2",
            )
        )
        state.requested_epoch = 1

    with SqlAlchemyContentUowFactory(factory)() as uow:
        projected = uow.topology_projection.project_next_batch(
            "library",
            limit=500,
            projected_at=_NOW,
        )
        assert projected.processed_volume_count == 2
        assert not projected.work_remaining
        uow.commit()

    with factory() as session:
        assert (
            session.scalar(select(func.count()).select_from(VolumeProcessingFact)) == 2
        )


def _seed_ten_thousand_asset_manifest(
    factory: sessionmaker[Session],
) -> CanonicalRequiredManifestFacts:
    with factory.begin() as session:
        session.add_all(
            (
                _library(),
                _root(),
                WorkVersion(id="version", library_id="library"),
                LibraryVolume(
                    id="volume",
                    library_id="library",
                    reading_morphology=ReadingMorphology.AUDIO.value,
                    content_state=VolumeContentState.PENDING,
                    content_revision=0,
                    required_manifest_revision=0,
                    optional_manifest_revision=0,
                    metadata_revision=0,
                    required_manifest_digest=None,
                    publication_fingerprint=None,
                    created_at=_NOW,
                    updated_at=_NOW,
                ),
            )
        )
        session.flush()
        unit = TopologyUnit(
            id="unit",
            library_id="library",
            unit_kind=TopologyUnitKind.MULTI_ASSET_VOLUME,
            work_owner_id=None,
            version_owner_id=None,
            volume_owner_id="volume",
            active_revision_id=None,
            created_at=_NOW,
        )
        session.add(unit)
        session.flush()
        session.add(
            TopologyUnitRevision(
                id="topology-revision",
                library_id="library",
                unit_id="unit",
                scan_run_id=None,
                reconcile_origin_id="seed-origin",
                unit_root_entry_id="root",
                revision=1,
                state=RevisionState.ACTIVE,
                created_at=_NOW,
            )
        )
        session.flush()
        session.add(
            TopologyVolumeProjection(
                id="volume-projection",
                library_id="library",
                unit_revision_id="topology-revision",
                volume_id="volume",
                version_id="version",
                root_entry_id="root",
                source_kind=SourceKind.MULTI_ASSET_AUDIO,
                reading_morphology=ReadingMorphology.AUDIO.value,
                structure_key="volume",
                source_name="audiobook",
                sort_key="audiobook",
            )
        )
        unit.active_revision_id = "topology-revision"
        session.flush()
        required_assets: list[RequiredContentAsset] = []
        for start in range(0, 10_000, 500):
            stop = start + 500
            sources: list[LibrarySourceEntry] = []
            volume_assets: list[VolumeAsset] = []
            content_facts: list[SourceContentFact] = []
            memberships: list[TopologyAssetMembership] = []
            for index in range(start, stop):
                source_id = f"source-{index:05d}"
                asset_id = f"asset-{index:05d}"
                digest = Sha256Digest.from_bytes(index.to_bytes(4, "big"))
                required_assets.append(
                    RequiredContentAsset(
                        asset_id=asset_id,
                        role=DomainAssetRole.AUDIO_TRACK,
                        source_format=SourceFormat.MP3,
                        size_bytes=64,
                        content_digest=digest,
                        order=index,
                        mime_type=canonical_required_mime_type(SourceFormat.MP3),
                    )
                )
                sources.append(
                    LibrarySourceEntry(
                        id=source_id,
                        library_id="library",
                        parent_entry_id="root",
                        local_name=f"track-{index:05d}.mp3",
                        local_name_key=f"track-{index:05d}.mp3",
                        entry_type=SourceEntryType.FILE,
                        filesystem_identity=f"dev:{source_id}",
                        size_bytes=64,
                        modified_ns=10,
                        last_seen_generation=1,
                        absence_confirmed_at=None,
                        children_presence_epoch=0,
                        next_children_presence_epoch=0,
                        observed_parent_presence_epoch=0,
                        pending_observed_parent_presence_epoch=None,
                        layout_state=LayoutState.PRESENT,
                        slot_state=SlotState.ACTIVE,
                        created_at=_NOW,
                        updated_at=_NOW,
                    )
                )
                volume_assets.append(
                    VolumeAsset(
                        id=asset_id,
                        library_id="library",
                        source_format=SourceFormat.MP3.value,
                        mime_type=None,
                        size_bytes=None,
                        content_digest=None,
                        validation_state=AssetValidationState.PENDING,
                        created_at=_NOW,
                        updated_at=_NOW,
                    )
                )
                content_facts.append(
                    SourceContentFact(
                        library_id="library",
                        source_entry_id=source_id,
                        input_revision=1,
                        work_revision=0,
                        digest_input_revision=1,
                        admission=AdmissionKind.AUDIO_TRACK.value,
                        source_format=SourceFormat.MP3.value,
                        filesystem_identity=f"dev:{source_id}",
                        device_id=1,
                        file_id=index + 1,
                        size_bytes=64,
                        modified_ns=10,
                        policy_version=1,
                        origin_kind=ContentOriginKind.FULL_SCAN,
                        origin_id="seed-scan",
                        origin_sequence=1,
                        available_at=_NOW,
                        state=SourceContentState.READY,
                        content_digest=digest.value,
                        lease_owner=None,
                        lease_expires_at=None,
                        created_at=_NOW,
                        updated_at=_NOW,
                    )
                )
                memberships.append(
                    TopologyAssetMembership(
                        id=f"membership-{index:05d}",
                        library_id="library",
                        unit_revision_id="topology-revision",
                        asset_id=asset_id,
                        volume_id="volume",
                        source_entry_id=source_id,
                        role=AssetRole.AUDIO_TRACK,
                        source_format=SourceFormat.MP3.value,
                        disc_number=None,
                        asset_order=index,
                        required_for_reading=True,
                    )
                )
            session.add_all((*sources, *volume_assets))
            session.flush()
            session.add_all((*content_facts, *memberships))
            session.flush()
        facts = CanonicalRequiredManifestFacts(
            topology_version=1,
            reading_morphology=ReadingMorphology.AUDIO,
            delivery_policy=RequiredDeliveryPolicy.ORIGINAL_SOURCE,
            delivery_policy_version=1,
            assets=tuple(required_assets),
        )
        session.add(
            VolumeProcessingFact(
                library_id="library",
                volume_id="volume",
                processor_kind=StoredContentProcessorKind.REQUIRED_MANIFEST,
                work_revision=1,
                processor_version="required-manifest-v1",
                active_topology_revision_id="topology-revision",
                expected_content_revision=0,
                expected_required_manifest_revision=0,
                input_fingerprint=facts.fingerprints.delivery_facts_digest.value,
                available_at=_NOW,
                state=ProcessorState.PENDING,
                failure_code=None,
                lease_owner=None,
                lease_expires_at=None,
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
    return facts


def test_ten_thousand_asset_manifest_append_and_finalize_are_statement_bounded(
    persistence,
) -> None:
    engine, factory = persistence
    expected_facts = _seed_ten_thousand_asset_manifest(factory)
    statement_count = [0]
    phase = ["setup"]
    asset_updates: dict[str, int] = {}

    def count_statement(*_args: object) -> None:
        statement_count[0] += 1

    def count_asset_update(
        _mapper: object,
        _connection: object,
        _asset: VolumeAsset,
    ) -> None:
        asset_updates[phase[0]] = asset_updates.get(phase[0], 0) + 1

    event.listen(engine, "before_cursor_execute", count_statement)
    event.listen(VolumeAsset, "after_update", count_asset_update)
    try:
        fence = _claim_manifest(factory)
        with SqlAlchemyContentUowFactory(factory)() as uow:
            candidate = uow.required_manifests.load_candidate(
                fence,
                manifest_id="manifest",
            )
            assert candidate is not None
            assert candidate.facts.fingerprints == expected_facts.fingerprints
            impact = required_manifest_revision_impact(
                None,
                candidate.facts.fingerprints,
                base_content_revision=0,
                base_required_manifest_revision=0,
            )
            staging = uow.required_manifests.begin_staging(
                fence,
                candidate,
                impact,
                created_at=_NOW,
            )
            assert staging is not None
            uow.commit()

        for start in range(0, 10_000, 500):
            phase[0] = f"append-{start}"
            with SqlAlchemyContentUowFactory(factory)() as uow:
                renewed = uow.processing.heartbeat(
                    fence,
                    now=_NOW,
                    lease_expires_at=_NOW + timedelta(minutes=5),
                )
                assert renewed is not None
                fence = renewed.fence()
                staging = uow.required_manifests.append_staging_batch(
                    fence,
                    staging,
                    RequiredManifestStageBatch(
                        start,
                        candidate.facts.assets[start : start + 500],
                        start == 9_500,
                    ),
                    staged_at=_NOW,
                )
                assert staging is not None
                uow.commit()
            assert asset_updates.get(phase[0], 0) <= 500

        phase[0] = "finalize"
        with SqlAlchemyContentUowFactory(factory)() as uow:
            renewed = uow.processing.heartbeat(
                fence,
                now=_NOW,
                lease_expires_at=_NOW + timedelta(minutes=5),
            )
            assert renewed is not None
            fence = renewed.fence()
            activated = uow.required_manifests.activate_staging(
                fence,
                staging,
                impact,
                activated_at=_NOW,
            )
            assert activated is not None
            uow.commit()
    finally:
        event.remove(VolumeAsset, "after_update", count_asset_update)
        event.remove(engine, "before_cursor_execute", count_statement)

    assert statement_count[0] < 500
    assert asset_updates.get("finalize", 0) == 0
    with factory() as session:
        assert (
            session.scalar(select(func.count()).select_from(VolumeManifestEntry))
            == 10_000
        )
        assert (
            session.scalar(select(func.count()).select_from(VolumeManifestHeader)) == 1
        )
