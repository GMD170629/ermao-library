from __future__ import annotations

import unicodedata
from datetime import UTC, datetime, timedelta

import pytest

from app.modules.catalog.application.scan_dto import (
    DiscoveredSource,
    DiscoveryEntryType,
    SourceObservation,
    SourcePathBinding,
    TargetedPathAbsent,
)
from app.modules.catalog.application.watcher_dto import (
    BoundProjectionKind,
    BoundTopologyProjection,
    BoundTopologyStageBatch,
    BoundTopologyUnitPlan,
    DirectoryPresenceEpoch,
    PendingSourceObservation,
    PresenceFoldPage,
    ReconcileIntent,
    ReconcileIntentPhase,
    ReconcileIntentState,
    SourceRebindDisposition,
    SourceRebindRejectionReason,
    SourceRebindResult,
    WatcherState,
    required_topology_source_paths,
)
from app.modules.catalog.domain.model import (
    AssetCandidate,
    OrganizationMode,
    PathComparison,
    SourceFormat,
    SourceKind,
    VolumeCandidate,
)
from app.modules.catalog.domain.scan import (
    TopologyUnitPlan,
    VersionProjectionPlan,
    VolumeProjectionPlan,
    build_topology_activation_groups,
)
from app.modules.catalog.domain.watcher import (
    FullRescanReason,
    ReconcileMoveEvidence,
    WatcherEntryHint,
    WatcherMovedEntryType,
    WatcherMoveEvent,
    WatcherPathEvent,
    WatcherPathEventKind,
    WatcherTrustLostReason,
    event_reconcile_scopes,
    full_rescan_reason,
    merge_reconcile_scopes,
    reconcile_scope,
)

NOW = datetime(2026, 8, 18, tzinfo=UTC)


def test_scope_preserves_raw_name_but_compares_nfc_and_casefolded() -> None:
    decomposed = unicodedata.normalize("NFD", "Fóo")

    decomposed_scope = reconcile_scope(
        (decomposed, "child"), PathComparison.INSENSITIVE
    )
    composed_scope = reconcile_scope(("fóo",), PathComparison.INSENSITIVE)

    assert decomposed_scope.relative_path == (decomposed,)
    assert decomposed_scope.comparison_key == composed_scope.comparison_key


def test_case_only_move_keeps_both_raw_scopes_and_exact_move_pair() -> None:
    event = WatcherMoveEvent(
        source_path=("Book", "old.epub"),
        destination_path=("book", "new.epub"),
        entry_type=WatcherMovedEntryType.FILE,
    )

    scopes = event_reconcile_scopes(event, PathComparison.INSENSITIVE)
    evidence = ReconcileMoveEvidence(
        source_path=event.source_path,
        destination_path=event.destination_path,
        entry_type=event.entry_type,
    )

    assert tuple(scope.relative_path for scope in scopes) == (("Book",), ("book",))
    assert scopes[0].comparison_key == scopes[1].comparison_key
    assert evidence.destination_path == ("book", "new.epub")


def test_scope_merge_requires_full_scan_at_third_distinct_raw_scope() -> None:
    first = (reconcile_scope(("a",), PathComparison.SENSITIVE),)
    second = (reconcile_scope(("b",), PathComparison.SENSITIVE),)
    third = (reconcile_scope(("c",), PathComparison.SENSITIVE),)

    assert merge_reconcile_scopes((first,), second) == (*first, *second)
    assert merge_reconcile_scopes((first, second), third) is None


@pytest.mark.parametrize(
    ("trust_reason", "rescan_reason"),
    [
        (WatcherTrustLostReason.DISCONNECTED, FullRescanReason.DISCONNECTED),
        (
            WatcherTrustLostReason.BACKEND_OVERFLOW,
            FullRescanReason.BACKEND_OVERFLOW,
        ),
        (WatcherTrustLostReason.UNTRUSTED, FullRescanReason.UNTRUSTED),
        (WatcherTrustLostReason.ROOT_BINDING_LOST, FullRescanReason.ROOT_CHANGED),
    ],
)
def test_trust_loss_has_a_stable_full_rescan_reason(
    trust_reason: WatcherTrustLostReason,
    rescan_reason: FullRescanReason,
) -> None:
    assert full_rescan_reason(trust_reason) is rescan_reason


def test_root_path_is_not_a_targeted_path_event() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        WatcherPathEvent(
            kind=WatcherPathEventKind.MODIFY,
            relative_path=(),
            entry_hint=WatcherEntryHint.DIRECTORY,
        )
    with pytest.raises(ValueError, match="must not be empty"):
        TargetedPathAbsent(())


def test_stable_paths_reject_surrogates_without_normalizing_nfd() -> None:
    decomposed = unicodedata.normalize("NFD", "é")

    assert TargetedPathAbsent((decomposed,)).relative_path == (decomposed,)
    with pytest.raises(ValueError, match="strict UTF-8"):
        ReconcileMoveEvidence(
            source_path=("\ud800",),
            destination_path=("valid",),
            entry_type=WatcherMovedEntryType.FILE,
        )


def test_watcher_state_pairs_constant_rescan_sequence_and_reason() -> None:
    state = WatcherState(
        library_id="library-1",
        latest_sequence=9,
        overflow_through_sequence=9,
        full_rescan_reason=FullRescanReason.JOURNAL_CAPACITY,
    )

    assert state.overflow_through_sequence == 9
    with pytest.raises(ValueError, match="must be paired"):
        WatcherState(
            library_id="library-1",
            latest_sequence=9,
            overflow_through_sequence=9,
            full_rescan_reason=None,
        )


def test_collision_recheck_has_a_dedicated_full_scan_reason() -> None:
    assert FullRescanReason.COLLISION_RECHECK.value == "COLLISION_RECHECK"


def test_reconcile_intent_enforces_sequence_and_lease_shapes() -> None:
    scope = reconcile_scope(("work",), PathComparison.SENSITIVE)
    intent = ReconcileIntent(
        intent_id="intent-1",
        library_id="library-1",
        first_sequence=3,
        through_sequence=7,
        scopes=(scope,),
        move_evidence=None,
        state=ReconcileIntentState.PENDING,
        phase=ReconcileIntentPhase.EXECUTE,
        lease_owner=None,
        lease_expires_at=None,
        topology_writer_fence=None,
        attempt=0,
        available_at=NOW,
        fold_after_source_entry_id=None,
        config_revision=1,
        organization_mode=OrganizationMode.VOLUMES,
        topology_version=1,
        path_comparison=PathComparison.SENSITIVE,
        root_path_snapshot="/library",
        root_identity_snapshot="dev:inode",
        created_at=NOW,
        updated_at=NOW,
    )

    assert intent.first_sequence == 3
    assert intent.through_sequence == 7
    with pytest.raises(ValueError, match="first_sequence"):
        ReconcileIntent(
            **{
                **{
                    field: getattr(intent, field)
                    for field in intent.__dataclass_fields__
                },
                "first_sequence": 8,
            }
        )
    with pytest.raises(ValueError, match="writer lease"):
        ReconcileIntent(
            **{
                field: (
                    ReconcileIntentState.RUNNING
                    if field == "state"
                    else getattr(intent, field)
                )
                for field in intent.__dataclass_fields__
            }
        )


def test_directory_attempt_epoch_can_skip_abandoned_proposals() -> None:
    binding = SourcePathBinding(
        ("work", "edition"),
        "source-1",
        "dev:inode",
        pending_parent_presence_epoch=9,
    )

    epoch = DirectoryPresenceEpoch(
        directory=binding,
        base_epoch=4,
        proposed_epoch=9,
    )

    assert epoch.proposed_epoch == 9
    assert binding.pending_parent_presence_epoch == 9

    with pytest.raises(ValueError, match="pending_parent_presence_epoch"):
        SourcePathBinding(
            ("work", "edition"),
            "source-1",
            "dev:inode",
            pending_parent_presence_epoch=0,
        )


def test_pending_observation_epoch_shape_follows_physical_parent() -> None:
    top_level = SourceObservation(
        DiscoveredSource(("work",), DiscoveryEntryType.DIRECTORY, "dev:work", None),
        1,
        None,
    )
    nested = SourceObservation(
        DiscoveredSource(
            ("work", "edition"),
            DiscoveryEntryType.DIRECTORY,
            "dev:edition",
            None,
        ),
        1,
        None,
    )

    assert PendingSourceObservation(top_level, None).pending_parent_epoch is None
    assert PendingSourceObservation(nested, 7).pending_parent_epoch == 7
    with pytest.raises(ValueError, match="top-level observations"):
        PendingSourceObservation(top_level, 7)
    with pytest.raises(ValueError, match="nested observations"):
        PendingSourceObservation(nested, None)

    with pytest.raises(ValueError, match="synthetic-root child"):
        SourcePathBinding(
            ("work",),
            "source-1",
            "dev:inode",
            pending_parent_presence_epoch=9,
        )


def test_source_rebind_result_is_discriminated() -> None:
    binding = SourcePathBinding(("renamed.epub",), "source-1", "dev:inode")
    applied = SourceRebindResult(
        disposition=SourceRebindDisposition.PRESERVED_MOVED_ID,
        binding=binding,
        rejection_reason=None,
    )
    rejected = SourceRebindResult(
        disposition=SourceRebindDisposition.NOT_PROVEN,
        binding=None,
        rejection_reason=SourceRebindRejectionReason.IDENTITY_AMBIGUOUS,
    )

    assert applied.binding == binding
    assert rejected.rejection_reason is SourceRebindRejectionReason.IDENTITY_AMBIGUOUS


def test_incomplete_presence_fold_page_requires_progress_cursor() -> None:
    with pytest.raises(ValueError, match="requires progress"):
        PresenceFoldPage(0, None, False)


def test_running_intent_requires_all_lease_fields() -> None:
    scope = reconcile_scope(("book.epub",), PathComparison.SENSITIVE)
    running = ReconcileIntent(
        intent_id="intent-1",
        library_id="library-1",
        first_sequence=1,
        through_sequence=1,
        scopes=(scope,),
        move_evidence=None,
        state=ReconcileIntentState.RUNNING,
        phase=ReconcileIntentPhase.FOLD,
        lease_owner="worker-1",
        lease_expires_at=NOW + timedelta(seconds=60),
        topology_writer_fence=5,
        attempt=1,
        available_at=NOW,
        fold_after_source_entry_id="source-9",
        config_revision=1,
        organization_mode=OrganizationMode.FLAT,
        topology_version=1,
        path_comparison=PathComparison.SENSITIVE,
        root_path_snapshot="/library",
        root_identity_snapshot="dev:inode",
        created_at=NOW,
        updated_at=NOW,
    )

    assert running.fold_after_source_entry_id == "source-9"


def _flat_plan() -> tuple[TopologyUnitPlan, tuple[SourcePathBinding, ...]]:
    path = ("book.epub",)
    groups = build_topology_activation_groups(
        OrganizationMode.FLAT,
        (
            VolumeCandidate(
                work_path=path,
                version_path=None,
                volume_path=path,
                source_kind=SourceKind.SINGLE_FILE,
                assets=(
                    AssetCandidate(
                        path=path,
                        source_format=SourceFormat.EPUB,
                        disc_number=0,
                        order=0,
                    ),
                ),
            ),
        ),
        path_comparison=PathComparison.SENSITIVE,
    )
    return groups[0].units[0], (SourcePathBinding(path, "source-1", "dev:1"),)


def test_bound_topology_plan_requires_typed_stable_id_shapes() -> None:
    raw_plan, source_bindings = _flat_plan()
    bindings = (
        BoundTopologyProjection(
            0,
            BoundProjectionKind.WORK,
            "work-1",
            None,
            None,
            "source-1",
            None,
            "work-key",
        ),
        BoundTopologyProjection(
            1,
            BoundProjectionKind.VERSION,
            "version-1",
            "work-1",
            BoundProjectionKind.WORK,
            None,
            None,
            "version-key",
        ),
        BoundTopologyProjection(
            2,
            BoundProjectionKind.VOLUME,
            "volume-1",
            "version-1",
            BoundProjectionKind.VERSION,
            "source-1",
            None,
            "volume-key",
        ),
        BoundTopologyProjection(
            3,
            BoundProjectionKind.ASSET,
            "asset-1",
            "volume-1",
            BoundProjectionKind.VOLUME,
            None,
            "source-1",
            None,
        ),
    )

    bound = BoundTopologyUnitPlan(
        plan=raw_plan,
        unit_id="unit-1",
        owner_stable_id="volume-1",
        source_bindings=source_bindings,
        projections=bindings,
    )

    assert bound.unit_id == "unit-1"
    with pytest.raises(ValueError, match="kinds must match"):
        BoundTopologyUnitPlan(
            plan=raw_plan,
            unit_id="unit-1",
            owner_stable_id="volume-1",
            source_bindings=source_bindings,
            projections=(
                BoundTopologyProjection(
                    0,
                    BoundProjectionKind.VOLUME,
                    "volume-x",
                    "version-x",
                    BoundProjectionKind.VERSION,
                    "source-1",
                    None,
                    "wrong-kind",
                ),
                *bindings[1:],
            ),
        )


def test_bound_staging_batch_carries_every_opaque_binding() -> None:
    raw_plan, source_bindings = _flat_plan()
    bound = BoundTopologyUnitPlan(
        plan=raw_plan,
        unit_id="unit-1",
        owner_stable_id="volume-1",
        source_bindings=source_bindings,
        projections=(
            BoundTopologyProjection(
                0,
                BoundProjectionKind.WORK,
                "work-1",
                None,
                None,
                "source-1",
                None,
                "work-key",
            ),
            BoundTopologyProjection(
                1,
                BoundProjectionKind.VERSION,
                "version-1",
                "work-1",
                BoundProjectionKind.WORK,
                None,
                None,
                "version-key",
            ),
            BoundTopologyProjection(
                2,
                BoundProjectionKind.VOLUME,
                "volume-1",
                "version-1",
                BoundProjectionKind.VERSION,
                "source-1",
                None,
                "volume-key",
            ),
            BoundTopologyProjection(
                3,
                BoundProjectionKind.ASSET,
                "asset-1",
                "volume-1",
                BoundProjectionKind.VOLUME,
                None,
                "source-1",
                None,
            ),
        ),
    )

    batch = BoundTopologyStageBatch(
        first_row=1,
        rows=raw_plan.rows[1:],
        bindings=bound.projections[1:],
        complete=True,
    )

    assert tuple(value.stable_id for value in batch.bindings) == (
        "version-1",
        "volume-1",
        "asset-1",
    )


def test_bound_topology_plan_rejects_asset_as_unit_owner() -> None:
    raw_plan, source_bindings = _flat_plan()
    projections = (
        BoundTopologyProjection(
            0,
            BoundProjectionKind.WORK,
            "work-1",
            None,
            None,
            "source-1",
            None,
            "work-key",
        ),
        BoundTopologyProjection(
            1,
            BoundProjectionKind.VERSION,
            "version-1",
            "work-1",
            BoundProjectionKind.WORK,
            None,
            None,
            "version-key",
        ),
        BoundTopologyProjection(
            2,
            BoundProjectionKind.VOLUME,
            "volume-1",
            "version-1",
            BoundProjectionKind.VERSION,
            "source-1",
            None,
            "volume-key",
        ),
        BoundTopologyProjection(
            3,
            BoundProjectionKind.ASSET,
            "asset-1",
            "volume-1",
            BoundProjectionKind.VOLUME,
            None,
            "source-1",
            None,
        ),
    )

    with pytest.raises(ValueError, match="VOLUME projection"):
        BoundTopologyUnitPlan(
            plan=raw_plan,
            unit_id="unit-1",
            owner_stable_id="asset-1",
            source_bindings=source_bindings,
            projections=projections,
        )


def test_bound_topology_plan_rejects_wrong_typed_parent_relation() -> None:
    raw_plan, source_bindings = _flat_plan()
    projections = (
        BoundTopologyProjection(
            0,
            BoundProjectionKind.WORK,
            "work-1",
            None,
            None,
            "source-1",
            None,
            "work-key",
        ),
        BoundTopologyProjection(
            1,
            BoundProjectionKind.VERSION,
            "version-1",
            "work-1",
            BoundProjectionKind.WORK,
            None,
            None,
            "version-key",
        ),
        BoundTopologyProjection(
            2,
            BoundProjectionKind.VOLUME,
            "volume-1",
            "work-1",
            BoundProjectionKind.VERSION,
            "source-1",
            None,
            "volume-key",
        ),
        BoundTopologyProjection(
            3,
            BoundProjectionKind.ASSET,
            "asset-1",
            "volume-1",
            BoundProjectionKind.VOLUME,
            None,
            "source-1",
            None,
        ),
    )

    with pytest.raises(ValueError, match="typed parent"):
        BoundTopologyUnitPlan(
            plan=raw_plan,
            unit_id="unit-1",
            owner_stable_id="volume-1",
            source_bindings=source_bindings,
            projections=projections,
        )


def test_volumes_bound_plans_require_explicit_ancestor_source_bindings() -> None:
    work = ("Work",)
    version = ("Work", "Edition")
    volume = ("Work", "Edition", "book.epub")
    groups = build_topology_activation_groups(
        OrganizationMode.VOLUMES,
        (
            VolumeCandidate(
                work_path=work,
                version_path=version,
                volume_path=volume,
                source_kind=SourceKind.SINGLE_FILE,
                assets=(
                    AssetCandidate(
                        path=volume,
                        source_format=SourceFormat.EPUB,
                        disc_number=0,
                        order=0,
                    ),
                ),
            ),
        ),
        path_comparison=PathComparison.SENSITIVE,
    )
    work_plan, version_plan, volume_plan = groups[0].units

    assert required_topology_source_paths(work_plan) == (work,)
    assert required_topology_source_paths(version_plan) == (work, version)
    assert required_topology_source_paths(volume_plan) == (work, version, volume)

    version_row = version_plan.rows[0]
    assert isinstance(version_row, VersionProjectionPlan)
    with pytest.raises(ValueError, match="exactly cover"):
        BoundTopologyUnitPlan(
            plan=version_plan,
            unit_id="unit-version",
            owner_stable_id="version-1",
            source_bindings=(SourcePathBinding(version, "source-version", "dev:2"),),
            projections=(
                BoundTopologyProjection(
                    0,
                    BoundProjectionKind.VERSION,
                    "version-1",
                    "work-1",
                    BoundProjectionKind.WORK,
                    "source-version",
                    None,
                    version_row.structure_key,
                ),
            ),
        )

    volume_row, _asset_row = volume_plan.rows
    assert isinstance(volume_row, VolumeProjectionPlan)
    with pytest.raises(ValueError, match="exactly cover"):
        BoundTopologyUnitPlan(
            plan=volume_plan,
            unit_id="unit-volume",
            owner_stable_id="volume-1",
            source_bindings=(SourcePathBinding(volume, "source-volume", "dev:3"),),
            projections=(
                BoundTopologyProjection(
                    0,
                    BoundProjectionKind.VOLUME,
                    "volume-1",
                    "version-1",
                    BoundProjectionKind.VERSION,
                    "source-volume",
                    None,
                    volume_row.structure_key,
                ),
                BoundTopologyProjection(
                    1,
                    BoundProjectionKind.ASSET,
                    "asset-1",
                    "volume-1",
                    BoundProjectionKind.VOLUME,
                    None,
                    "source-volume",
                    None,
                ),
            ),
        )


def test_disc_asset_requires_every_physical_ancestor_binding() -> None:
    work = ("Work",)
    version = ("Work", "Edition")
    volume = ("Work", "Edition", "Audio")
    disc = ("Work", "Edition", "Audio", "Disc 1")
    track = ("Work", "Edition", "Audio", "Disc 1", "track.mp3")
    groups = build_topology_activation_groups(
        OrganizationMode.VOLUMES,
        (
            VolumeCandidate(
                work_path=work,
                version_path=version,
                volume_path=volume,
                source_kind=SourceKind.MULTI_ASSET_AUDIO,
                assets=(
                    AssetCandidate(
                        path=track,
                        source_format=SourceFormat.MP3,
                        disc_number=1,
                        order=0,
                    ),
                ),
            ),
        ),
        path_comparison=PathComparison.SENSITIVE,
    )

    assert required_topology_source_paths(groups[0].units[2]) == (
        work,
        version,
        volume,
        disc,
        track,
    )
