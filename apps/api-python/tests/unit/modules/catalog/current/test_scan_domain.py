from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from app.modules.catalog.application.scan_dto import (
    DiscoveredSource,
    DiscoveryEntryType,
    FullScanRun,
    ScanFailureCode,
    SourceObservation,
)
from app.modules.catalog.application.source_admission_ports import SourceStatExpectation
from app.modules.catalog.domain.admission import (
    AdmissionRejectionReason,
    SourceAdmissionRejection,
)
from app.modules.catalog.domain.model import (
    AssetCandidate,
    EntryType,
    OrganizationMode,
    PathComparison,
    SourceFormat,
    SourceKind,
    VolumeCandidate,
)
from app.modules.catalog.domain.scan import (
    AssetMembershipPlan,
    AssetRole,
    ReadingMorphology,
    ScanStage,
    ScanState,
    TopologyUnitKind,
    TopologyUnitPlan,
    VersionProjectionPlan,
    VolumeProjectionPlan,
    WorkProjectionPlan,
    build_topology_activation_groups,
    iter_stage_batches,
    reading_morphology,
)


def single_file(
    path: tuple[str, ...],
    *,
    work_path: tuple[str, ...] | None = None,
    version_path: tuple[str, ...] | None = None,
    source_format: SourceFormat = SourceFormat.EPUB,
) -> VolumeCandidate:
    return VolumeCandidate(
        work_path=work_path or path,
        version_path=version_path,
        volume_path=path,
        source_kind=SourceKind.SINGLE_FILE,
        assets=(AssetCandidate(path, source_format, 0),),
    )


def audio_volume(
    work_path: tuple[str, ...],
    volume_path: tuple[str, ...],
    count: int,
) -> VolumeCandidate:
    return VolumeCandidate(
        work_path=work_path,
        version_path=None,
        volume_path=volume_path,
        source_kind=SourceKind.MULTI_ASSET_AUDIO,
        assets=tuple(
            AssetCandidate(
                (*volume_path, f"track-{index}.mp3"),
                SourceFormat.MP3,
                index,
            )
            for index in range(count)
        ),
    )


@pytest.mark.parametrize(
    ("formats", "expected"),
    (
        ((SourceFormat.EPUB,), ReadingMorphology.REFLOWABLE),
        ((SourceFormat.PDF,), ReadingMorphology.PDF),
        ((SourceFormat.CBZ,), ReadingMorphology.COMIC),
        ((SourceFormat.MP3, SourceFormat.M4B), ReadingMorphology.AUDIO),
    ),
)
def test_reading_morphology_is_format_evidence_only(
    formats: tuple[SourceFormat, ...], expected: ReadingMorphology
) -> None:
    assert reading_morphology(formats) is expected


def test_flat_plan_keeps_work_version_volume_in_one_owned_revision() -> None:
    groups = build_topology_activation_groups(
        OrganizationMode.FLAT,
        (single_file(("Book 10.epub",)), single_file(("Book 2.epub",))),
        path_comparison=PathComparison.SENSITIVE,
    )
    assert [group.units[0].owner_path for group in groups] == [
        ("Book 2.epub",),
        ("Book 10.epub",),
    ]
    assert all(
        group.units[0].unit_kind is TopologyUnitKind.FLAT_VOLUME for group in groups
    )
    assert [type(row) for row in groups[0].units[0].rows] == [
        WorkProjectionPlan,
        VersionProjectionPlan,
        VolumeProjectionPlan,
        AssetMembershipPlan,
    ]


def test_volumes_plan_uses_references_and_atomic_parent_child_group() -> None:
    work = ("Work",)
    version = ("Work", "Edition")
    volume = ("Work", "Edition", "Volume 1.epub")
    group = build_topology_activation_groups(
        OrganizationMode.VOLUMES,
        (
            single_file(
                volume,
                work_path=work,
                version_path=version,
            ),
        ),
        path_comparison=PathComparison.SENSITIVE,
    )[0]
    assert tuple(unit.unit_kind for unit in group.units) == (
        TopologyUnitKind.WORK_CONTAINER,
        TopologyUnitKind.VERSION_CONTAINER,
        TopologyUnitKind.SINGLE_FILE_VOLUME,
    )
    assert [type(row) for row in group.units[0].rows] == [WorkProjectionPlan]
    assert [type(row) for row in group.units[1].rows] == [VersionProjectionPlan]
    assert [type(row) for row in group.units[2].rows] == [
        VolumeProjectionPlan,
        AssetMembershipPlan,
    ]
    version_row = group.units[1].rows[0]
    volume_row = group.units[2].rows[0]
    assert isinstance(version_row, VersionProjectionPlan)
    assert version_row.work_path == work
    assert isinstance(volume_row, VolumeProjectionPlan)
    assert volume_row.work_path == work
    assert volume_row.version_path == version


def test_projection_source_names_preserve_legal_whitespace_components() -> None:
    work = (" ",)
    version = (" ", "  ")
    volume = (" ", "  ", "   ")

    group = build_topology_activation_groups(
        OrganizationMode.VOLUMES,
        (single_file(volume, work_path=work, version_path=version),),
        path_comparison=PathComparison.SENSITIVE,
    )[0]

    assert group.units[0].rows[0].source_name == " "
    assert group.units[1].rows[0].source_name == "  "
    assert group.units[2].rows[0].source_name == "   "


def test_topology_plan_rejects_wrong_container_ownership_and_mutable_rows() -> None:
    unit = build_topology_activation_groups(
        OrganizationMode.VOLUMES,
        (
            single_file(
                ("Work", "Edition", "Volume.epub"),
                work_path=("Work",),
                version_path=("Work", "Edition"),
            ),
        ),
        path_comparison=PathComparison.SENSITIVE,
    )[0].units[0]

    with pytest.raises(ValueError, match="match its owner"):
        TopologyUnitPlan(
            unit_key=unit.unit_key,
            unit_kind=unit.unit_kind,
            owner_path=("Other",),
            unit_root_path=("Other",),
            rows=unit.rows,
        )
    with pytest.raises(TypeError, match="rows must be a tuple"):
        TopologyUnitPlan(
            unit_key=unit.unit_key,
            unit_kind=unit.unit_kind,
            owner_path=unit.owner_path,
            unit_root_path=unit.unit_root_path,
            rows=list(unit.rows),
        )


def test_source_observation_rejects_cross_path_or_entry_type_admission() -> None:
    source = DiscoveredSource(
        relative_path=("A.epub",),
        entry_type=DiscoveryEntryType.FILE,
        filesystem_identity="dev:1",
        expected_stat=SourceStatExpectation(1, 1, 10, 1),
    )

    with pytest.raises(ValueError, match="path must match"):
        SourceObservation(
            source=source,
            generation=1,
            admission=SourceAdmissionRejection(
                relative_path=("B.epub",),
                entry_type=EntryType.FILE,
                reason=AdmissionRejectionReason.UNSUPPORTED_EXTENSION,
            ),
        )
    with pytest.raises(ValueError, match="entry type must match"):
        SourceObservation(
            source=source,
            generation=1,
            admission=SourceAdmissionRejection(
                relative_path=("A.epub",),
                entry_type=EntryType.SYMLINK,
                reason=AdmissionRejectionReason.SYMLINK_NOT_ALLOWED,
            ),
        )


def test_audiobook_is_one_work_group_with_many_volumes_and_bounded_batches() -> None:
    work = ("Audiobook",)
    groups = build_topology_activation_groups(
        OrganizationMode.AUDIOBOOK,
        (
            audio_volume(work, (*work, "Volume 1"), 600),
            audio_volume(work, (*work, "Volume 2"), 600),
        ),
        path_comparison=PathComparison.SENSITIVE,
    )
    assert len(groups) == 1
    unit = groups[0].units[0]
    assert unit.unit_kind is TopologyUnitKind.AUDIOBOOK_WORK
    batches = tuple(iter_stage_batches(unit))
    assert [len(batch.rows) for batch in batches] == [500, 500, 204]
    assert [batch.complete for batch in batches] == [False, False, True]


def test_audiobook_track_limit_is_enforced_across_volumes() -> None:
    work = ("Audiobook",)
    with pytest.raises(ValueError, match="10,000"):
        build_topology_activation_groups(
            OrganizationMode.AUDIOBOOK,
            (
                audio_volume(work, (*work, "Volume 1"), 5_001),
                audio_volume(work, (*work, "Volume 2"), 5_000),
            ),
            path_comparison=PathComparison.SENSITIVE,
        )


@pytest.mark.parametrize(
    ("mode", "candidate", "expected_roles"),
    (
        (
            OrganizationMode.FLAT,
            single_file(("Track.mp3",), source_format=SourceFormat.MP3),
            (AssetRole.PRIMARY,),
        ),
        (
            OrganizationMode.VOLUMES,
            single_file(
                ("Work", "Edition", "Track.m4a"),
                work_path=("Work",),
                version_path=("Work", "Edition"),
                source_format=SourceFormat.M4A,
            ),
            (AssetRole.PRIMARY,),
        ),
        (
            OrganizationMode.AUDIOBOOK,
            audio_volume(("Work",), ("Work", "Volume"), 2),
            (AssetRole.AUDIO_TRACK, AssetRole.AUDIO_TRACK),
        ),
        (
            OrganizationMode.AUDIOBOOK,
            single_file(("Root Track.m4b",), source_format=SourceFormat.M4B),
            (AssetRole.PRIMARY,),
        ),
        (
            OrganizationMode.AUDIOBOOK,
            single_file(("Root Track.mp3",), source_format=SourceFormat.MP3),
            (AssetRole.PRIMARY,),
        ),
    ),
)
def test_asset_role_comes_from_source_ownership_not_reader_morphology(
    mode: OrganizationMode,
    candidate: VolumeCandidate,
    expected_roles: tuple[AssetRole, ...],
) -> None:
    groups = build_topology_activation_groups(
        mode,
        (candidate,),
        path_comparison=PathComparison.SENSITIVE,
    )

    assert (
        tuple(
            row.role
            for group in groups
            for unit in group.units
            for row in unit.rows
            if isinstance(row, AssetMembershipPlan)
        )
        == expected_roles
    )


def make_run(
    state: ScanState,
    stage: ScanStage,
    *,
    lease: bool,
) -> FullScanRun:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    live = state in {ScanState.PENDING, ScanState.RUNNING, ScanState.FINALIZING}
    started = None if state is ScanState.PENDING else now
    return FullScanRun(
        scan_id="scan-1",
        library_id="library-1",
        canonical_root="/srv/books",
        generation=1,
        config_revision=2,
        organization_mode=OrganizationMode.FLAT,
        topology_version=1,
        path_comparison=PathComparison.SENSITIVE,
        root_identity=None if state is ScanState.PENDING else "dev:1",
        topology_writer_fence=3,
        state=state,
        failure_code=(ScanFailureCode.IO_ERROR if state is ScanState.FAILED else None),
        stage=stage,
        lease_owner="worker" if lease else None,
        lease_expires_at=now + timedelta(minutes=1) if lease else None,
        heartbeat_at=now if live else None,
        discovered_count=0,
        diagnostic_count=0,
        created_by_actor_id="admin",
        started_at=started,
        finished_at=None if live else now,
        watcher_sequence_watermark=0,
    )


def test_scan_state_stage_and_lease_matrix() -> None:
    assert (
        make_run(ScanState.PENDING, ScanStage.DISCOVER, lease=True).root_identity
        is None
    )
    assert make_run(ScanState.RUNNING, ScanStage.RECONCILE, lease=True).root_identity
    assert make_run(ScanState.FINALIZING, ScanStage.FINALIZE, lease=True).fence()
    assert make_run(ScanState.COMPLETED, ScanStage.FINALIZE, lease=False).finished_at

    with pytest.raises(ValueError, match="finalizing"):
        make_run(ScanState.FINALIZING, ScanStage.RECONCILE, lease=True)
    with pytest.raises(ValueError, match="terminal scans cannot retain"):
        make_run(ScanState.COMPLETED, ScanStage.FINALIZE, lease=True)
    with pytest.raises(ValueError, match="non-terminal scans require"):
        make_run(ScanState.RUNNING, ScanStage.DISCOVER, lease=False)


def test_historical_or_live_scan_may_outlive_its_deleted_creator() -> None:
    run = make_run(ScanState.RUNNING, ScanStage.DISCOVER, lease=True)

    detached = replace(run, created_by_actor_id=None)

    assert detached.created_by_actor_id is None
    assert detached.fence() == run.fence()
