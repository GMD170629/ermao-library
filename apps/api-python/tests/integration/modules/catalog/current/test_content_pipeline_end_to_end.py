from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.current.bootstrap import bootstrap_system
from app.db.current.engine import create_current_engine
from app.db.current.runner import upgrade_current_schema
from app.modules.catalog.application.content_dto import (
    ContentRunDisposition,
    RequiredManifestActivationDisposition,
    RequiredOpeningDisposition,
    RequiredOpeningEvidence,
    RequiredOpeningProgress,
    RequiredOpeningRequest,
    RunNextContentTopologyProjectionCommand,
    RunNextRequiredManifestCommand,
    RunNextRequiredOpeningCommand,
    RunNextSourceDigestCommand,
    SourceDigestEvidence,
    SourceDigestPublishDisposition,
    SourceDigestRequest,
)
from app.modules.catalog.application.content_ports import (
    ContentUnitOfWork,
    ContentUowFactory,
    RequiredOpeningCheckpointPort,
    SourceDigestCheckpointPort,
    SourceDigestIoError,
    SourceDigestPort,
)
from app.modules.catalog.application.content_processing import (
    RunNextContentTopologyProjection,
    RunNextRequiredManifest,
    RunNextRequiredOpening,
    RunNextSourceDigest,
)
from app.modules.catalog.domain.content import (
    CanonicalRequiredManifestFacts,
    ContentProcessorKind,
    RequiredContentAsset,
    RequiredDeliveryPolicy,
    Sha256Digest,
    canonical_required_mime_type,
)
from app.modules.catalog.domain.model import (
    AdmissionKind,
    OrganizationMode,
    PathComparison,
    SourceFormat,
    SourceKind,
)
from app.modules.catalog.domain.scan import AssetRole as DomainAssetRole
from app.modules.catalog.domain.scan import ReadingMorphology
from app.modules.catalog.infrastructure.content import LocalSourceDigestAdapter
from app.modules.catalog.infrastructure.persistence import (
    AssetRole,
    AssetValidationState,
    CatalogLibrary,
    CatalogOutbox,
    ContentOriginKind,
    ContentTopologyProjectionState,
    LayoutState,
    LibraryControlState,
    LibraryHealth,
    LibrarySourceEntry,
    LibraryVolume,
    LibraryWork,
    ManifestKind,
    ProcessorState,
    RequiredManifestState,
    RevisionState,
    SlotState,
    SourceContentFact,
    SourceContentState,
    SourceEntryType,
    SqlAlchemyContentUowFactory,
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

_NOW = datetime(2026, 8, 18, 12, tzinfo=UTC)
_LIBRARY_ID = "library-e2e"
_VOLUME_ID = "volume-e2e"
_SOURCE_ID = "source-e2e"
_ROOT_ID = "root-e2e"
_ASSET_ID = "asset-e2e"
_UNIT_ID = "unit-e2e"
_TOPOLOGY_REVISION_ID = "topology-revision-e2e"
_PUBLICATION_FINGERPRINT = Sha256Digest.from_bytes(b"publication-e2e")


@dataclass(frozen=True, slots=True)
class _Scenario:
    engine: Engine
    factory: sessionmaker[Session]
    root: Path
    source: Path


class _Clock:
    def now(self) -> datetime:
        return _NOW


class _Monotonic:
    def seconds(self) -> float:
        return 0.0


class _Ids:
    def __init__(self, *values: str) -> None:
        self._values = iter(values)

    def new_id(self) -> str:
        return next(self._values)


class _Opening:
    def __init__(self) -> None:
        self.requests: list[RequiredOpeningRequest] = []

    def inspect(
        self,
        request: RequiredOpeningRequest,
        checkpoint: RequiredOpeningCheckpointPort,
    ) -> RequiredOpeningEvidence:
        self.requests.append(request)
        bytes_read = 0
        for source_index, source in enumerate(request.sources, start=1):
            if source.expected_stat.size_bytes:
                bytes_read += 1
                checkpoint.checkpoint(
                    RequiredOpeningProgress(
                        request.volume_id,
                        request.topology_unit_revision_id,
                        bytes_read,
                        source_index - 1,
                    )
                )
            checkpoint.checkpoint(
                RequiredOpeningProgress(
                    request.volume_id,
                    request.topology_unit_revision_id,
                    bytes_read,
                    source_index,
                )
            )
        return RequiredOpeningEvidence(
            RequiredOpeningDisposition.READY,
            publication_fingerprint=_PUBLICATION_FINGERPRINT,
        )


class _InspectingUowFactory:
    """Observe the committed STAGING snapshot before final activation."""

    def __init__(
        self,
        base: ContentUowFactory,
        inspect_before_final: Callable[[], bool],
    ) -> None:
        self._base = base
        self._inspect_before_final = inspect_before_final
        self.calls = 0
        self.observed_complete_staging = False

    def __call__(self) -> ContentUnitOfWork:
        self.calls += 1
        if not self.observed_complete_staging:
            self.observed_complete_staging = self._inspect_before_final()
        return self._base()


class _FailingDigest(SourceDigestPort):
    def __init__(self, invalidate: Callable[[], None]) -> None:
        self._invalidate = invalidate

    def digest(
        self,
        request: SourceDigestRequest,
        checkpoint: SourceDigestCheckpointPort,
    ) -> SourceDigestEvidence:
        del request, checkpoint
        self._invalidate()
        raise SourceDigestIoError()


def _root_identity(path: Path) -> str:
    observed = path.stat()
    return f"{observed.st_dev}:{observed.st_ino}"


def _source_identity(path: Path) -> str:
    observed = path.stat()
    return f"{observed.st_dev}:{observed.st_ino}"


def _facts(
    digest: Sha256Digest,
    *,
    asset_id: str = _ASSET_ID,
    size_bytes: int,
) -> CanonicalRequiredManifestFacts:
    return CanonicalRequiredManifestFacts(
        topology_version=1,
        reading_morphology=ReadingMorphology.PDF,
        delivery_policy=RequiredDeliveryPolicy.ORIGINAL_SOURCE,
        delivery_policy_version=1,
        assets=(
            RequiredContentAsset(
                asset_id=asset_id,
                role=DomainAssetRole.PRIMARY,
                source_format=SourceFormat.PDF,
                size_bytes=size_bytes,
                content_digest=digest,
                order=0,
                mime_type=canonical_required_mime_type(SourceFormat.PDF),
            ),
        ),
    )


def _seed(scenario: _Scenario) -> None:
    root_stat = scenario.root.stat()
    source_stat = scenario.source.stat()
    with scenario.factory.begin() as session:
        session.add(
            CatalogLibrary(
                id=_LIBRARY_ID,
                name="E2E Library",
                root_path=str(scenario.root.resolve()),
                root_path_key=str(scenario.root.resolve()),
                organization_mode=OrganizationMode.FLAT,
                topology_version=1,
                path_comparison=PathComparison.SENSITIVE,
                write_policy=WritePolicy.READ_ONLY,
                control_state=LibraryControlState.ACTIVE,
                observed_health=LibraryHealth.HEALTHY,
                config_revision=1,
                topology_writer_fence=1,
                next_scan_generation=2,
                last_successful_generation=1,
                last_successful_scan_at=_NOW,
            )
        )
        session.flush()
        session.add(
            ContentTopologyProjectionState(
                library_id=_LIBRARY_ID,
                requested_epoch=0,
                claimed_epoch=0,
                applied_epoch=0,
                cursor_volume_id=None,
                updated_at=_NOW,
            )
        )
        session.add(
            LibrarySourceEntry(
                id=_ROOT_ID,
                library_id=_LIBRARY_ID,
                parent_entry_id=None,
                local_name="$root",
                local_name_key="$root",
                entry_type=SourceEntryType.SYNTHETIC_ROOT,
                filesystem_identity=f"{root_stat.st_dev}:{root_stat.st_ino}",
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
        )
        session.flush()
        session.add(
            LibrarySourceEntry(
                id=_SOURCE_ID,
                library_id=_LIBRARY_ID,
                parent_entry_id=_ROOT_ID,
                local_name=scenario.source.name,
                local_name_key=scenario.source.name,
                entry_type=SourceEntryType.FILE,
                filesystem_identity=f"{source_stat.st_dev}:{source_stat.st_ino}",
                size_bytes=source_stat.st_size,
                modified_ns=source_stat.st_mtime_ns,
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
        session.add_all(
            (
                LibraryWork(id="work-e2e", library_id=_LIBRARY_ID),
                WorkVersion(id="version-e2e", library_id=_LIBRARY_ID),
                LibraryVolume(
                    id=_VOLUME_ID,
                    library_id=_LIBRARY_ID,
                    reading_morphology=ReadingMorphology.PDF.value,
                    content_state=VolumeContentState.PENDING,
                    content_revision=0,
                    required_manifest_revision=0,
                    optional_manifest_revision=7,
                    metadata_revision=11,
                    required_manifest_digest=None,
                    publication_fingerprint=None,
                    created_at=_NOW,
                    updated_at=_NOW,
                ),
                VolumeAsset(
                    id=_ASSET_ID,
                    library_id=_LIBRARY_ID,
                    source_format=SourceFormat.PDF.value,
                    mime_type=None,
                    size_bytes=None,
                    content_digest=None,
                    validation_state=AssetValidationState.PENDING,
                    created_at=_NOW,
                    updated_at=_NOW,
                ),
                SourceContentFact(
                    library_id=_LIBRARY_ID,
                    source_entry_id=_SOURCE_ID,
                    input_revision=1,
                    work_revision=0,
                    digest_input_revision=None,
                    admission=AdmissionKind.PRIMARY.value,
                    source_format=SourceFormat.PDF.value,
                    filesystem_identity=f"{source_stat.st_dev}:{source_stat.st_ino}",
                    device_id=source_stat.st_dev,
                    file_id=source_stat.st_ino,
                    size_bytes=source_stat.st_size,
                    modified_ns=source_stat.st_mtime_ns,
                    policy_version=1,
                    origin_kind=ContentOriginKind.FULL_SCAN,
                    origin_id="seed-scan-e2e",
                    origin_sequence=1,
                    available_at=_NOW,
                    state=SourceContentState.PENDING,
                    content_digest=None,
                    lease_owner=None,
                    lease_expires_at=None,
                    created_at=_NOW,
                    updated_at=_NOW,
                ),
            )
        )
        session.flush()
        unit = TopologyUnit(
            id=_UNIT_ID,
            library_id=_LIBRARY_ID,
            unit_kind=TopologyUnitKind.SINGLE_FILE_VOLUME,
            work_owner_id=None,
            version_owner_id=None,
            volume_owner_id=_VOLUME_ID,
            active_revision_id=None,
            created_at=_NOW,
        )
        session.add(unit)
        session.flush()
        session.add(
            TopologyUnitRevision(
                id=_TOPOLOGY_REVISION_ID,
                library_id=_LIBRARY_ID,
                unit_id=_UNIT_ID,
                scan_run_id=None,
                reconcile_origin_id="seed-reconcile-e2e",
                unit_root_entry_id=_SOURCE_ID,
                revision=1,
                state=RevisionState.ACTIVE,
                created_at=_NOW,
            )
        )
        session.flush()
        session.add_all(
            (
                TopologyVolumeProjection(
                    id="volume-projection-e2e",
                    library_id=_LIBRARY_ID,
                    unit_revision_id=_TOPOLOGY_REVISION_ID,
                    volume_id=_VOLUME_ID,
                    version_id="version-e2e",
                    root_entry_id=_SOURCE_ID,
                    source_kind=SourceKind.SINGLE_FILE,
                    reading_morphology=ReadingMorphology.PDF.value,
                    structure_key="volume-e2e",
                    source_name=scenario.source.name,
                    sort_key=scenario.source.name,
                ),
                TopologyAssetMembership(
                    id="membership-e2e",
                    library_id=_LIBRARY_ID,
                    unit_revision_id=_TOPOLOGY_REVISION_ID,
                    asset_id=_ASSET_ID,
                    volume_id=_VOLUME_ID,
                    source_entry_id=_SOURCE_ID,
                    role=AssetRole.PRIMARY,
                    source_format=SourceFormat.PDF.value,
                    disc_number=None,
                    asset_order=0,
                    required_for_reading=True,
                ),
            )
        )
        unit.active_revision_id = _TOPOLOGY_REVISION_ID


@pytest.fixture
def scenario(tmp_path: Path) -> Iterator[_Scenario]:
    root = tmp_path / "library"
    root.mkdir()
    source = root / "book.pdf"
    source.write_bytes(b"a" * 4096)
    database_path = tmp_path / "content-e2e.sqlite3"
    upgrade_current_schema(database_path)
    engine = create_current_engine(database_path)
    bootstrap_system(engine)
    value = _Scenario(
        engine,
        sessionmaker(engine, expire_on_commit=False),
        root,
        source,
    )
    _seed(value)
    try:
        yield value
    finally:
        engine.dispose()


def _content_factory(scenario: _Scenario) -> ContentUowFactory:
    return cast(ContentUowFactory, SqlAlchemyContentUowFactory(scenario.factory))


def _run_digest(
    scenario: _Scenario,
    digest_port: SourceDigestPort | None = None,
):
    return RunNextSourceDigest(
        unit_of_work_factory=_content_factory(scenario),
        digest_port=digest_port or LocalSourceDigestAdapter(),
        clock=_Clock(),
        monotonic_clock=_Monotonic(),
    ).execute(RunNextSourceDigestCommand(_LIBRARY_ID, "digest-worker"))


def _run_manifest(
    scenario: _Scenario,
    manifest_id: str,
    *,
    unit_of_work_factory: ContentUowFactory | None = None,
):
    return RunNextRequiredManifest(
        unit_of_work_factory=unit_of_work_factory or _content_factory(scenario),
        id_generator=_Ids(manifest_id),
        clock=_Clock(),
    ).execute(RunNextRequiredManifestCommand(_LIBRARY_ID, "manifest-worker"))


def _run_opening(scenario: _Scenario, opening: _Opening):
    return RunNextRequiredOpening(
        unit_of_work_factory=_content_factory(scenario),
        opening_port=opening,
        clock=_Clock(),
        monotonic_clock=_Monotonic(),
    ).execute(RunNextRequiredOpeningCommand(_LIBRARY_ID, "opening-worker"))


def _run_topology_projection(scenario: _Scenario):
    return RunNextContentTopologyProjection(
        unit_of_work_factory=_content_factory(scenario),
        clock=_Clock(),
    ).execute(RunNextContentTopologyProjectionCommand(_LIBRARY_ID))


def _complete_initial_pipeline(scenario: _Scenario) -> None:
    digest = _run_digest(scenario)
    assert digest.disposition is ContentRunDisposition.COMPLETED
    assert digest.publication is SourceDigestPublishDisposition.READY_CHANGED
    manifest = _run_manifest(scenario, "manifest-initial")
    assert manifest.disposition is ContentRunDisposition.COMPLETED
    opening = _run_opening(scenario, _Opening())
    assert opening.disposition is ContentRunDisposition.COMPLETED


def _active_manifest(session: Session) -> VolumeManifestHeader:
    active = session.scalar(
        select(VolumeManifestHeader).where(
            VolumeManifestHeader.library_id == _LIBRARY_ID,
            VolumeManifestHeader.volume_id == _VOLUME_ID,
            VolumeManifestHeader.kind == ManifestKind.REQUIRED,
            VolumeManifestHeader.state == RequiredManifestState.ACTIVE,
        )
    )
    assert active is not None
    return active


def _force_manifest_pending(
    session: Session,
    *,
    topology_revision_id: str,
    input_fingerprint: Sha256Digest,
) -> None:
    volume = session.get(LibraryVolume, _VOLUME_ID)
    processing = session.get(
        VolumeProcessingFact,
        (_LIBRARY_ID, _VOLUME_ID, StoredContentProcessorKind.REQUIRED_MANIFEST),
    )
    assert volume is not None and processing is not None
    processing.work_revision += 1
    processing.processor_version = "required-manifest-v1"
    processing.active_topology_revision_id = topology_revision_id
    processing.expected_content_revision = volume.content_revision
    processing.expected_required_manifest_revision = volume.required_manifest_revision
    processing.input_fingerprint = input_fingerprint.value
    processing.available_at = _NOW
    processing.state = ProcessorState.PENDING
    processing.failure_code = None
    processing.lease_owner = None
    processing.lease_expires_at = None
    processing.updated_at = _NOW


def _force_source_rehash(
    scenario: _Scenario,
    *,
    advance_input_revision: bool,
    observed_stat: os.stat_result,
) -> None:
    pending_fingerprint = Sha256Digest.from_bytes(b"pending-source-e2e")
    with scenario.factory.begin() as session:
        source = session.get(LibrarySourceEntry, _SOURCE_ID)
        fact = session.get(SourceContentFact, (_LIBRARY_ID, _SOURCE_ID))
        volume = session.get(LibraryVolume, _VOLUME_ID)
        asset = session.get(VolumeAsset, _ASSET_ID)
        assert source is not None and fact is not None
        assert volume is not None and asset is not None
        source.filesystem_identity = _source_identity(scenario.source)
        source.size_bytes = observed_stat.st_size
        source.modified_ns = observed_stat.st_mtime_ns
        source.updated_at = _NOW
        if advance_input_revision:
            fact.input_revision += 1
        fact.work_revision += 1
        fact.filesystem_identity = _source_identity(scenario.source)
        fact.device_id = observed_stat.st_dev
        fact.file_id = observed_stat.st_ino
        fact.size_bytes = observed_stat.st_size
        fact.modified_ns = observed_stat.st_mtime_ns
        fact.available_at = _NOW
        fact.state = SourceContentState.PENDING
        fact.lease_owner = None
        fact.lease_expires_at = None
        fact.updated_at = _NOW
        volume.content_state = VolumeContentState.PENDING
        volume.updated_at = _NOW
        asset.validation_state = AssetValidationState.PENDING
        asset.updated_at = _NOW
        _force_manifest_pending(
            session,
            topology_revision_id=_TOPOLOGY_REVISION_ID,
            input_fingerprint=pending_fingerprint,
        )


def _assert_old_active_and_complete_staging(
    scenario: _Scenario,
    *,
    expected_active_id: str,
    expected_revisions: tuple[int, int],
) -> bool:
    with scenario.factory() as session:
        headers = tuple(
            session.scalars(
                select(VolumeManifestHeader)
                .where(VolumeManifestHeader.volume_id == _VOLUME_ID)
                .order_by(VolumeManifestHeader.id)
            )
        )
        if len(headers) != 2:
            return False
        active = next(
            header for header in headers if header.state is RequiredManifestState.ACTIVE
        )
        staging = next(
            header
            for header in headers
            if header.state is RequiredManifestState.STAGING
        )
        if staging.staged_entry_count != staging.expected_entry_count:
            return False
        assert active.id == expected_active_id
        volume = session.get(LibraryVolume, _VOLUME_ID)
        assert volume is not None
        assert (
            volume.content_revision,
            volume.required_manifest_revision,
        ) == expected_revisions
        return True


def test_initial_pipeline_publishes_only_at_complete_manifest_and_opening(
    scenario: _Scenario,
) -> None:
    digest = _run_digest(scenario)
    assert digest.publication is SourceDigestPublishDisposition.READY_CHANGED
    with scenario.factory() as session:
        volume = session.get(LibraryVolume, _VOLUME_ID)
        assert volume is not None
        assert (volume.content_revision, volume.required_manifest_revision) == (0, 0)
        assert (
            session.scalar(select(func.count()).select_from(VolumeManifestHeader)) == 0
        )

    manifest = _run_manifest(scenario, "manifest-initial")
    assert manifest.disposition is ContentRunDisposition.COMPLETED
    with scenario.factory() as session:
        volume = session.get(LibraryVolume, _VOLUME_ID)
        assert volume is not None
        assert (volume.content_revision, volume.required_manifest_revision) == (1, 1)
        assert volume.content_state is VolumeContentState.PENDING
        assert _active_manifest(session).id == "manifest-initial"

    opening = _Opening()
    opened = _run_opening(scenario, opening)
    assert opened.disposition is ContentRunDisposition.COMPLETED
    with scenario.factory() as session:
        volume = session.get(LibraryVolume, _VOLUME_ID)
        assert volume is not None
        assert volume.content_state is VolumeContentState.READY
        assert volume.publication_fingerprint == _PUBLICATION_FINGERPRINT.value
        assert (volume.optional_manifest_revision, volume.metadata_revision) == (7, 11)


def test_same_canonical_manifest_reuses_active_and_opening_uses_current_stat(
    scenario: _Scenario,
) -> None:
    _complete_initial_pipeline(scenario)
    original_stat = scenario.source.stat()
    os.utime(
        scenario.source,
        ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns + 1_000_000_000),
    )
    current_stat = scenario.source.stat()
    assert current_stat.st_mtime_ns != original_stat.st_mtime_ns
    _force_source_rehash(
        scenario,
        advance_input_revision=True,
        observed_stat=current_stat,
    )
    with scenario.factory.begin() as session:
        opening = session.get(
            VolumeProcessingFact,
            (_LIBRARY_ID, _VOLUME_ID, StoredContentProcessorKind.REQUIRED_OPENING),
        )
        assert opening is not None
        opening.processor_version = "required-opening-v0"

    digest = _run_digest(scenario)
    assert digest.publication is SourceDigestPublishDisposition.READY_CHANGED
    manifest = _run_manifest(scenario, "unused-same-canonical")
    assert manifest.disposition is ContentRunDisposition.COMPLETED
    with scenario.factory() as session:
        assert _active_manifest(session).id == "manifest-initial"
        volume = session.get(LibraryVolume, _VOLUME_ID)
        assert volume is not None
        assert (volume.content_revision, volume.required_manifest_revision) == (1, 1)

    opening_port = _Opening()
    opening_result = _run_opening(scenario, opening_port)
    assert opening_result.disposition is ContentRunDisposition.COMPLETED
    assert len(opening_port.requests) == 1
    request = opening_port.requests[0]
    assert request.sources[0].expected_stat.modified_ns == current_stat.st_mtime_ns
    assert request.sources[0].expected_stat.file_id == current_stat.st_ino
    assert request.sources[0].content_digest == Sha256Digest.from_bytes(
        scenario.source.read_bytes()
    )


def test_new_asset_identity_with_same_source_bytes_advances_both_axes(
    scenario: _Scenario,
) -> None:
    _complete_initial_pipeline(scenario)
    digest = Sha256Digest.from_bytes(scenario.source.read_bytes())
    candidate = _facts(
        digest,
        asset_id="asset-rebound-e2e",
        size_bytes=scenario.source.stat().st_size,
    )
    with scenario.factory.begin() as session:
        old_revision = session.get(TopologyUnitRevision, _TOPOLOGY_REVISION_ID)
        unit = session.get(TopologyUnit, _UNIT_ID)
        volume = session.get(LibraryVolume, _VOLUME_ID)
        assert old_revision is not None and unit is not None and volume is not None
        old_revision.state = RevisionState.SUPERSEDED
        session.add(
            VolumeAsset(
                id="asset-rebound-e2e",
                library_id=_LIBRARY_ID,
                source_format=SourceFormat.PDF.value,
                mime_type=None,
                size_bytes=None,
                content_digest=None,
                validation_state=AssetValidationState.PENDING,
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        session.add(
            TopologyUnitRevision(
                id="topology-revision-rebound-e2e",
                library_id=_LIBRARY_ID,
                unit_id=_UNIT_ID,
                scan_run_id=None,
                reconcile_origin_id="rebind-e2e",
                unit_root_entry_id=_SOURCE_ID,
                revision=2,
                state=RevisionState.ACTIVE,
                created_at=_NOW,
            )
        )
        session.flush()
        session.add_all(
            (
                TopologyVolumeProjection(
                    id="volume-projection-rebound-e2e",
                    library_id=_LIBRARY_ID,
                    unit_revision_id="topology-revision-rebound-e2e",
                    volume_id=_VOLUME_ID,
                    version_id="version-e2e",
                    root_entry_id=_SOURCE_ID,
                    source_kind=SourceKind.SINGLE_FILE,
                    reading_morphology=ReadingMorphology.PDF.value,
                    structure_key="volume-e2e",
                    source_name=scenario.source.name,
                    sort_key=scenario.source.name,
                ),
                TopologyAssetMembership(
                    id="membership-rebound-e2e",
                    library_id=_LIBRARY_ID,
                    unit_revision_id="topology-revision-rebound-e2e",
                    asset_id="asset-rebound-e2e",
                    volume_id=_VOLUME_ID,
                    source_entry_id=_SOURCE_ID,
                    role=AssetRole.PRIMARY,
                    source_format=SourceFormat.PDF.value,
                    disc_number=None,
                    asset_order=0,
                    required_for_reading=True,
                ),
            )
        )
        unit.active_revision_id = "topology-revision-rebound-e2e"
        volume.content_state = VolumeContentState.PENDING
        _force_manifest_pending(
            session,
            topology_revision_id="topology-revision-rebound-e2e",
            input_fingerprint=candidate.fingerprints.delivery_facts_digest,
        )

    with scenario.factory() as session:
        previous = _active_manifest(session)
        previous_id = previous.id
        previous_source_bytes = previous.source_bytes_digest
        previous_content = previous.content_facts_digest

    inspecting = _InspectingUowFactory(
        _content_factory(scenario),
        lambda: _assert_old_active_and_complete_staging(
            scenario,
            expected_active_id=previous_id,
            expected_revisions=(1, 1),
        ),
    )
    result = _run_manifest(
        scenario,
        "manifest-rebound-e2e",
        unit_of_work_factory=inspecting,
    )
    assert result.disposition is ContentRunDisposition.COMPLETED
    assert inspecting.observed_complete_staging
    with scenario.factory() as session:
        active = _active_manifest(session)
        volume = session.get(LibraryVolume, _VOLUME_ID)
        assert volume is not None
        assert active.id == "manifest-rebound-e2e"
        assert active.source_bytes_digest == previous_source_bytes
        assert active.content_facts_digest != previous_content
        assert (volume.content_revision, volume.required_manifest_revision) == (2, 2)


def test_delivery_only_change_advances_only_required_manifest_revision(
    scenario: _Scenario,
) -> None:
    _complete_initial_pipeline(scenario)
    digest = Sha256Digest.from_bytes(scenario.source.read_bytes())
    candidate = _facts(digest, size_bytes=scenario.source.stat().st_size)
    with scenario.factory.begin() as session:
        active = _active_manifest(session)
        # Represent an ACTIVE manifest built by an older delivery canonicalizer:
        # source/content facts are identical, while delivery facts must republish.
        active.processor_version = "required-manifest-v0"
        active.delivery_facts_digest = Sha256Digest.from_bytes(
            b"previous-delivery-policy"
        ).value
        _force_manifest_pending(
            session,
            topology_revision_id=_TOPOLOGY_REVISION_ID,
            input_fingerprint=candidate.fingerprints.delivery_facts_digest,
        )

    result = _run_manifest(scenario, "manifest-delivery-e2e")
    assert result.disposition is ContentRunDisposition.COMPLETED
    with scenario.factory() as session:
        active = _active_manifest(session)
        volume = session.get(LibraryVolume, _VOLUME_ID)
        assert volume is not None
        assert active.id == "manifest-delivery-e2e"
        assert (
            active.source_bytes_digest
            == candidate.fingerprints.source_bytes_digest.value
        )
        assert (
            active.content_facts_digest
            == candidate.fingerprints.content_facts_digest.value
        )
        assert (
            active.delivery_facts_digest
            == candidate.fingerprints.delivery_facts_digest.value
        )
        assert (volume.content_revision, volume.required_manifest_revision) == (1, 2)
        assert volume.content_state is VolumeContentState.READY
        assert volume.publication_fingerprint == _PUBLICATION_FINGERPRINT.value


def test_same_stat_new_digest_keeps_old_active_until_final_manifest_cas(
    scenario: _Scenario,
) -> None:
    _complete_initial_pipeline(scenario)
    original_stat = scenario.source.stat()
    old_digest = Sha256Digest.from_bytes(scenario.source.read_bytes())
    scenario.source.write_bytes(b"b" * original_stat.st_size)
    os.utime(
        scenario.source,
        ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
    )
    restored_stat = scenario.source.stat()
    assert restored_stat.st_ino == original_stat.st_ino
    assert restored_stat.st_size == original_stat.st_size
    assert restored_stat.st_mtime_ns == original_stat.st_mtime_ns
    _force_source_rehash(
        scenario,
        advance_input_revision=False,
        observed_stat=restored_stat,
    )

    digest = _run_digest(scenario)
    assert digest.publication is SourceDigestPublishDisposition.INPUT_REVISION_ADVANCED
    with scenario.factory() as session:
        fact = session.get(SourceContentFact, (_LIBRARY_ID, _SOURCE_ID))
        volume = session.get(LibraryVolume, _VOLUME_ID)
        active = _active_manifest(session)
        assert fact is not None and volume is not None
        assert fact.input_revision == 2
        assert (
            fact.content_digest
            == Sha256Digest.from_bytes(scenario.source.read_bytes()).value
        )
        assert fact.content_digest != old_digest.value
        assert (volume.content_revision, volume.required_manifest_revision) == (1, 1)
        assert active.id == "manifest-initial"
        previous_manifest_id = active.id

    inspecting = _InspectingUowFactory(
        _content_factory(scenario),
        lambda: _assert_old_active_and_complete_staging(
            scenario,
            expected_active_id=previous_manifest_id,
            expected_revisions=(1, 1),
        ),
    )
    manifest = _run_manifest(
        scenario,
        "manifest-new-bytes-e2e",
        unit_of_work_factory=inspecting,
    )
    assert manifest.disposition is ContentRunDisposition.COMPLETED
    assert inspecting.observed_complete_staging
    with scenario.factory() as session:
        volume = session.get(LibraryVolume, _VOLUME_ID)
        assert volume is not None
        assert _active_manifest(session).id == "manifest-new-bytes-e2e"
        assert (volume.content_revision, volume.required_manifest_revision) == (2, 2)


def test_topology_pointer_blocks_old_manifest_until_same_content_retargets(
    scenario: _Scenario,
) -> None:
    _complete_initial_pipeline(scenario)
    next_revision_id = "topology-revision-next-e2e"
    with scenario.factory.begin() as session:
        previous = _active_manifest(session)
        previous_manifest_id = previous.id
        previous_entry_ids = tuple(
            session.scalars(
                select(VolumeManifestEntry.id).where(
                    VolumeManifestEntry.manifest_id == previous_manifest_id
                )
            )
        )
        unit = session.get(TopologyUnit, _UNIT_ID)
        opening = session.get(
            VolumeProcessingFact,
            (
                _LIBRARY_ID,
                _VOLUME_ID,
                StoredContentProcessorKind.REQUIRED_OPENING,
            ),
        )
        projection_state = session.get(
            ContentTopologyProjectionState,
            _LIBRARY_ID,
        )
        old_revision = session.get(TopologyUnitRevision, _TOPOLOGY_REVISION_ID)
        assert unit is not None and opening is not None and old_revision is not None
        assert projection_state is not None
        old_revision.state = RevisionState.SUPERSEDED
        session.flush()
        session.add(
            TopologyUnitRevision(
                id=next_revision_id,
                library_id=_LIBRARY_ID,
                unit_id=_UNIT_ID,
                scan_run_id=None,
                reconcile_origin_id="topology-successor-e2e",
                unit_root_entry_id=_SOURCE_ID,
                revision=2,
                state=RevisionState.ACTIVE,
                created_at=_NOW,
            )
        )
        session.flush()
        session.add_all(
            (
                TopologyVolumeProjection(
                    id="volume-projection-next-e2e",
                    library_id=_LIBRARY_ID,
                    unit_revision_id=next_revision_id,
                    volume_id=_VOLUME_ID,
                    version_id="version-e2e",
                    root_entry_id=_SOURCE_ID,
                    source_kind=SourceKind.SINGLE_FILE,
                    reading_morphology=ReadingMorphology.PDF.value,
                    structure_key="volume-e2e",
                    source_name=scenario.source.name,
                    sort_key=scenario.source.name,
                ),
                TopologyAssetMembership(
                    id="membership-next-e2e",
                    library_id=_LIBRARY_ID,
                    unit_revision_id=next_revision_id,
                    asset_id=_ASSET_ID,
                    volume_id=_VOLUME_ID,
                    source_entry_id=_SOURCE_ID,
                    role=AssetRole.PRIMARY,
                    source_format=SourceFormat.PDF.value,
                    disc_number=None,
                    asset_order=0,
                    required_for_reading=True,
                ),
            )
        )
        unit.active_revision_id = next_revision_id
        projection_state.requested_epoch = 1
        projection_state.updated_at = _NOW
        # Make the otherwise READY opening claimable.  Its old topology fence
        # must still make the claim defer after the pointer switch.
        opening.state = ProcessorState.PENDING
        opening.available_at = _NOW
        opening.lease_owner = None
        opening.lease_expires_at = None
        opening.updated_at = _NOW

    with scenario.factory() as session:
        current_unit = session.get(TopologyUnit, _UNIT_ID)
        volume = session.get(LibraryVolume, _VOLUME_ID)
        old_active = _active_manifest(session)
        assert current_unit is not None and volume is not None
        assert volume.content_state is VolumeContentState.READY
        assert current_unit.active_revision_id == next_revision_id
        assert old_active.topology_unit_revision_id == _TOPOLOGY_REVISION_ID
        assert old_active.topology_unit_revision_id != current_unit.active_revision_id

    with _content_factory(scenario)() as uow:
        blocked = uow.processing.claim_next(
            _LIBRARY_ID,
            ContentProcessorKind.REQUIRED_OPENING,
            owner_token="stale-opening-worker",
            now=_NOW,
            lease_expires_at=_NOW + timedelta(minutes=1),
            defer_until=_NOW + timedelta(seconds=30),
        )
        assert blocked.work is None
        assert blocked.deferred_count == 1
        uow.commit()

    projection = _run_topology_projection(scenario)
    assert projection.disposition is ContentRunDisposition.COMPLETED
    assert projection.processed_volume_count == 1
    assert not projection.work_remaining
    with scenario.factory() as session:
        volume = session.get(LibraryVolume, _VOLUME_ID)
        assert volume is not None
        assert volume.content_state is VolumeContentState.PENDING
        assert _active_manifest(session).topology_unit_revision_id != next_revision_id

    manifest = _run_manifest(scenario, "unused-same-content-manifest")
    assert manifest.disposition is ContentRunDisposition.COMPLETED
    assert manifest.activation is RequiredManifestActivationDisposition.REUSED_ACTIVE
    with scenario.factory() as session:
        active = _active_manifest(session)
        volume = session.get(LibraryVolume, _VOLUME_ID)
        assert volume is not None
        assert active.id == previous_manifest_id
        assert active.topology_unit_revision_id == next_revision_id
        assert (volume.content_revision, volume.required_manifest_revision) == (1, 1)
        assert (
            tuple(
                session.scalars(
                    select(VolumeManifestEntry.id).where(
                        VolumeManifestEntry.manifest_id == active.id
                    )
                )
            )
            == previous_entry_ids
        )

    opening_adapter = _Opening()
    opening_result = _run_opening(scenario, opening_adapter)
    assert opening_result.disposition is ContentRunDisposition.COMPLETED
    assert opening_adapter.requests[0].topology_unit_revision_id == next_revision_id
    with scenario.factory() as session:
        volume = session.get(LibraryVolume, _VOLUME_ID)
        assert volume is not None
        assert volume.content_state is VolumeContentState.READY
        assert (volume.content_revision, volume.required_manifest_revision) == (1, 1)


def test_projection_successors_finish_old_sweep_then_repair_prefix(
    scenario: _Scenario,
) -> None:
    trailing_volume_id = "volume-z-e2e"
    trailing_revision_id = "topology-revision-z-e2e"
    with scenario.factory.begin() as session:
        projection_state = session.get(
            ContentTopologyProjectionState,
            _LIBRARY_ID,
        )
        assert projection_state is not None
        session.add(
            LibraryVolume(
                id=trailing_volume_id,
                library_id=_LIBRARY_ID,
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
        session.flush()
        trailing_unit = TopologyUnit(
            id="unit-z-e2e",
            library_id=_LIBRARY_ID,
            unit_kind=TopologyUnitKind.SINGLE_FILE_VOLUME,
            work_owner_id=None,
            version_owner_id=None,
            volume_owner_id=trailing_volume_id,
            active_revision_id=None,
            created_at=_NOW,
        )
        session.add(trailing_unit)
        session.flush()
        session.add(
            TopologyUnitRevision(
                id=trailing_revision_id,
                library_id=_LIBRARY_ID,
                unit_id=trailing_unit.id,
                scan_run_id=None,
                reconcile_origin_id="trailing-origin-e2e",
                unit_root_entry_id=_ROOT_ID,
                revision=1,
                state=RevisionState.ACTIVE,
                created_at=_NOW,
            )
        )
        session.flush()
        session.add(
            TopologyVolumeProjection(
                id="volume-projection-z-e2e",
                library_id=_LIBRARY_ID,
                unit_revision_id=trailing_revision_id,
                volume_id=trailing_volume_id,
                version_id="version-e2e",
                root_entry_id=_ROOT_ID,
                source_kind=SourceKind.SINGLE_FILE,
                reading_morphology=ReadingMorphology.PDF.value,
                structure_key="volume-z-e2e",
                source_name="z.pdf",
                sort_key="z.pdf",
            )
        )
        trailing_unit.active_revision_id = trailing_revision_id
        projection_state.requested_epoch = 1
        projection_state.updated_at = _NOW

    with _content_factory(scenario)() as uow:
        first = uow.topology_projection.project_next_batch(
            _LIBRARY_ID,
            limit=1,
            projected_at=_NOW,
        )
        assert first.processed_volume_count == 1
        assert first.state.cursor_volume_id == _VOLUME_ID
        assert (
            first.state.requested_epoch,
            first.state.claimed_epoch,
            first.state.applied_epoch,
        ) == (1, 1, 0)
        uow.commit()

    successor_revision_id = "topology-revision-successor-e2e"
    with scenario.factory.begin() as session:
        unit = session.get(TopologyUnit, _UNIT_ID)
        projection_state = session.get(
            ContentTopologyProjectionState,
            _LIBRARY_ID,
        )
        old_revision = session.get(TopologyUnitRevision, _TOPOLOGY_REVISION_ID)
        assert unit is not None and projection_state is not None
        assert old_revision is not None
        old_revision.state = RevisionState.SUPERSEDED
        session.flush()
        session.add(
            TopologyUnitRevision(
                id=successor_revision_id,
                library_id=_LIBRARY_ID,
                unit_id=_UNIT_ID,
                scan_run_id=None,
                reconcile_origin_id="successor-origin-e2e",
                unit_root_entry_id=_SOURCE_ID,
                revision=2,
                state=RevisionState.ACTIVE,
                created_at=_NOW,
            )
        )
        session.flush()
        session.add(
            TopologyVolumeProjection(
                id="volume-projection-successor-e2e",
                library_id=_LIBRARY_ID,
                unit_revision_id=successor_revision_id,
                volume_id=_VOLUME_ID,
                version_id="version-e2e",
                root_entry_id=_SOURCE_ID,
                source_kind=SourceKind.SINGLE_FILE,
                reading_morphology=ReadingMorphology.PDF.value,
                structure_key="volume-e2e",
                source_name=scenario.source.name,
                sort_key=scenario.source.name,
            )
        )
        unit.active_revision_id = successor_revision_id
        # Model three serialized activations while the old sweep is active.
        # They must coalesce in one row without repeatedly resetting its cursor.
        projection_state.requested_epoch += 3
        projection_state.updated_at = _NOW

    with _content_factory(scenario)() as uow:
        old_tail = uow.topology_projection.project_next_batch(
            _LIBRARY_ID,
            limit=1,
            projected_at=_NOW + timedelta(seconds=1),
        )
        assert old_tail.processed_volume_count == 1
        assert old_tail.work_remaining
        assert (
            old_tail.state.requested_epoch,
            old_tail.state.claimed_epoch,
            old_tail.state.applied_epoch,
            old_tail.state.cursor_volume_id,
        ) == (4, 4, 1, None)
        uow.commit()

    with _content_factory(scenario)() as uow:
        repaired = uow.topology_projection.project_next_batch(
            _LIBRARY_ID,
            limit=1,
            projected_at=_NOW + timedelta(seconds=2),
        )
        assert repaired.processed_volume_count == 1
        assert not repaired.work_remaining
        assert (
            repaired.state.requested_epoch,
            repaired.state.claimed_epoch,
            repaired.state.applied_epoch,
            repaired.state.cursor_volume_id,
        ) == (4, 4, 4, None)
        uow.commit()

    with scenario.factory() as session:
        leading = session.get(
            VolumeProcessingFact,
            (
                _LIBRARY_ID,
                _VOLUME_ID,
                StoredContentProcessorKind.REQUIRED_MANIFEST,
            ),
        )
        trailing = session.get(
            VolumeProcessingFact,
            (
                _LIBRARY_ID,
                trailing_volume_id,
                StoredContentProcessorKind.REQUIRED_MANIFEST,
            ),
        )
        projection_state = session.get(
            ContentTopologyProjectionState,
            _LIBRARY_ID,
        )
        assert leading is not None and trailing is not None
        assert projection_state is not None
        assert leading.active_topology_revision_id == successor_revision_id
        assert trailing.active_topology_revision_id == trailing_revision_id
        assert projection_state.requested_epoch == 4
        assert projection_state.applied_epoch == 4
        assert projection_state.cursor_volume_id is None


@pytest.mark.parametrize("operational_failure", (False, True))
def test_stale_digest_success_and_failure_cannot_publish_or_emit(
    scenario: _Scenario,
    operational_failure: bool,
) -> None:
    _complete_initial_pipeline(scenario)
    _force_source_rehash(
        scenario,
        advance_input_revision=False,
        observed_stat=scenario.source.stat(),
    )
    with scenario.factory() as session:
        outbox_before = session.scalar(select(func.count()).select_from(CatalogOutbox))
        active_before = _active_manifest(session).id
        fact_before = session.get(SourceContentFact, (_LIBRARY_ID, _SOURCE_ID))
        processing_before = session.get(
            VolumeProcessingFact,
            (_LIBRARY_ID, _VOLUME_ID, StoredContentProcessorKind.REQUIRED_MANIFEST),
        )
        volume = session.get(LibraryVolume, _VOLUME_ID)
        assert fact_before is not None and processing_before is not None
        assert volume is not None and fact_before.content_digest is not None
        digest_before = fact_before.content_digest
        manifest_work_before = (
            processing_before.work_revision,
            processing_before.state,
            processing_before.input_fingerprint,
        )
        revisions_before = (
            volume.content_revision,
            volume.required_manifest_revision,
        )

    def invalidate_owned_work() -> None:
        with scenario.factory.begin() as session:
            fact = session.get(SourceContentFact, (_LIBRARY_ID, _SOURCE_ID))
            assert fact is not None and fact.state is SourceContentState.RUNNING
            fact.input_revision += 1
            fact.work_revision += 1
            fact.state = SourceContentState.PENDING
            fact.lease_owner = None
            fact.lease_expires_at = None
            fact.available_at = _NOW
            fact.updated_at = _NOW

    digest_port: SourceDigestPort = (
        _FailingDigest(invalidate_owned_work)
        if operational_failure
        else LocalSourceDigestAdapter(digest_completion_hook=invalidate_owned_work)
    )
    result = _run_digest(scenario, digest_port)
    assert result.disposition is ContentRunDisposition.STALE
    assert result.publication is None

    with scenario.factory() as session:
        fact = session.get(SourceContentFact, (_LIBRARY_ID, _SOURCE_ID))
        processing = session.get(
            VolumeProcessingFact,
            (_LIBRARY_ID, _VOLUME_ID, StoredContentProcessorKind.REQUIRED_MANIFEST),
        )
        volume = session.get(LibraryVolume, _VOLUME_ID)
        assert fact is not None and processing is not None and volume is not None
        assert fact.state is SourceContentState.PENDING
        assert fact.input_revision == 2
        assert fact.digest_input_revision == 1
        assert fact.content_digest == digest_before
        assert (
            processing.work_revision,
            processing.state,
            processing.input_fingerprint,
        ) == manifest_work_before
        assert _active_manifest(session).id == active_before
        assert (
            volume.content_revision,
            volume.required_manifest_revision,
        ) == revisions_before
        assert (
            session.scalar(select(func.count()).select_from(CatalogOutbox))
            == outbox_before
        )
