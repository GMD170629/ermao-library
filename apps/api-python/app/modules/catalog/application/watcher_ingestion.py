"""Bounded watcher event ingestion into coalesced reconcile intents."""

from __future__ import annotations

from datetime import datetime

from app.modules.catalog.application.content_dto import (
    ExplicitSourceModify,
    WatcherContentOrigin,
)
from app.modules.catalog.application.content_events import (
    ContentWakeReason,
    append_content_available,
)
from app.modules.catalog.application.ports import Clock, IdGenerator, OutboxEvent
from app.modules.catalog.application.watcher_dto import (
    FullRescanTransition,
    ReconcileIntent,
    ReconcileIntentPhase,
    ReconcileIntentState,
    RecordWatcherEventCommand,
    WatcherIngestDisposition,
    WatcherIngestResult,
    WatcherState,
)
from app.modules.catalog.application.watcher_ports import (
    WatcherUnitOfWork,
    WatcherUowFactory,
)
from app.modules.catalog.domain.library import LibraryControlState
from app.modules.catalog.domain.watcher import (
    MAX_PENDING_RECONCILE_INTENTS,
    MAX_RECONCILE_SCOPES,
    FullRescanReason,
    ReconcileMoveEvidence,
    WatcherEntryHint,
    WatcherMoveEvent,
    WatcherPathEvent,
    WatcherPathEventKind,
    WatcherStale,
    WatcherTrustLost,
    event_reconcile_scopes,
    full_rescan_reason,
    merge_reconcile_scopes,
)

_JOURNALING_LIBRARY_STATES = {
    LibraryControlState.ACTIVATING,
    LibraryControlState.ACTIVE,
    LibraryControlState.PAUSED,
}


def _append_reconcile_available(
    uow: WatcherUnitOfWork,
    *,
    library_id: str,
    sequence: int,
) -> None:
    uow.outbox.append(
        OutboxEvent(
            "LIBRARY_RECONCILE_AVAILABLE",
            library_id,
            "SYSTEM",
            (("sequence", sequence),),
        )
    )


def _append_full_scan_required(
    uow: WatcherUnitOfWork,
    *,
    transition: FullRescanTransition,
) -> None:
    state = transition.state
    reason = state.full_rescan_reason
    through_sequence = state.overflow_through_sequence
    if reason is None or through_sequence is None:
        raise WatcherStale()
    uow.outbox.append(
        OutboxEvent(
            "LIBRARY_FULL_SCAN_REQUIRED",
            state.library_id,
            "SYSTEM",
            (("reason", reason.value), ("throughSequence", through_sequence)),
        )
    )


class RecordWatcherEvent:
    """Allocate one sequence and journal or fence one trusted watcher event."""

    def __init__(
        self,
        *,
        unit_of_work_factory: WatcherUowFactory,
        id_generator: IdGenerator,
        clock: Clock,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._id_generator = id_generator
        self._clock = clock

    def execute(self, command: RecordWatcherEventCommand) -> WatcherIngestResult:
        now = self._clock.now()
        with self._unit_of_work_factory() as uow:
            library = uow.libraries.get_for_reconcile_for_update(command.library_id)
            if (
                library is None
                or library.control_state not in _JOURNALING_LIBRARY_STATES
            ):
                raise WatcherStale()
            state = uow.watcher.get_state_for_update(command.library_id)
            if state is None:
                raise WatcherStale()
            durable_root_identity = uow.sources.get_synthetic_root_identity(
                command.library_id
            )
            if durable_root_identity != command.root_identity:
                raise WatcherStale()
            sequence = state.latest_sequence + 1
            modification = self._explicit_modify(command, sequence=sequence)
            if state.full_rescan_reason is not None:
                return self._force_full_scan(
                    uow,
                    state,
                    state.full_rescan_reason,
                    now,
                    modification=modification,
                )
            if isinstance(command.event, WatcherTrustLost):
                return self._force_full_scan(
                    uow,
                    state,
                    full_rescan_reason(command.event.reason),
                    now,
                    modification=modification,
                )
            scopes = event_reconcile_scopes(command.event, library.path_comparison)
            overlapping = uow.watcher.find_overlapping_pending(
                command.library_id,
                scopes,
                limit=MAX_RECONCILE_SCOPES + 1,
            )
            merged_scopes = merge_reconcile_scopes(
                tuple(intent.scopes for intent in overlapping), scopes
            )
            if merged_scopes is None:
                return self._force_full_scan(
                    uow,
                    state,
                    FullRescanReason.JOURNAL_CAPACITY,
                    now,
                    modification=modification,
                )
            pending_ids = uow.watcher.pending_ids_up_to(
                command.library_id,
                limit=MAX_PENDING_RECONCILE_INTENTS + 1,
            )
            replaced_ids = tuple(value.intent_id for value in overlapping)
            if (
                len(pending_ids) - len(set(pending_ids).intersection(replaced_ids)) + 1
                > MAX_PENDING_RECONCILE_INTENTS
            ):
                return self._force_full_scan(
                    uow,
                    state,
                    FullRescanReason.JOURNAL_CAPACITY,
                    now,
                    modification=modification,
                )
            move_evidence = self._coalesced_move_evidence(command, overlapping)
            intent = ReconcileIntent(
                intent_id=self._id_generator.new_id(),
                library_id=library.library_id,
                first_sequence=min(
                    (value.first_sequence for value in overlapping),
                    default=sequence,
                ),
                through_sequence=sequence,
                scopes=merged_scopes,
                move_evidence=move_evidence,
                state=ReconcileIntentState.PENDING,
                phase=ReconcileIntentPhase.EXECUTE,
                lease_owner=None,
                lease_expires_at=None,
                topology_writer_fence=None,
                attempt=0,
                available_at=now,
                fold_after_source_entry_id=None,
                config_revision=library.config_revision,
                organization_mode=library.organization_mode,
                topology_version=library.topology_version,
                path_comparison=library.path_comparison,
                root_path_snapshot=library.canonical_root,
                root_identity_snapshot=command.root_identity,
                created_at=now,
                updated_at=now,
            )
            stored = uow.watcher.append_or_replace(
                expected_latest_sequence=state.latest_sequence,
                intent=intent,
                replaced_intent_ids=replaced_ids,
            )
            if stored is None:
                raise WatcherStale()
            self._record_explicit_modify(uow, modification, observed_at=now)
            if not overlapping:
                _append_reconcile_available(
                    uow,
                    library_id=command.library_id,
                    sequence=sequence,
                )
            uow.commit()
            return WatcherIngestResult(
                sequence=sequence,
                disposition=(
                    WatcherIngestDisposition.COALESCED
                    if overlapping
                    else WatcherIngestDisposition.QUEUED
                ),
                intent_id=stored.intent_id,
                full_rescan_reason=None,
            )

    @staticmethod
    def _explicit_modify(
        command: RecordWatcherEventCommand,
        *,
        sequence: int,
    ) -> ExplicitSourceModify | None:
        event = command.event
        if not (
            isinstance(event, WatcherPathEvent)
            and event.kind is WatcherPathEventKind.MODIFY
            and event.entry_hint is WatcherEntryHint.FILE
        ):
            return None
        return ExplicitSourceModify(
            library_id=command.library_id,
            relative_path=event.relative_path,
            origin=WatcherContentOrigin(sequence),
        )

    @staticmethod
    def _coalesced_move_evidence(
        command: RecordWatcherEventCommand,
        overlapping: tuple[ReconcileIntent, ...],
    ) -> ReconcileMoveEvidence | None:
        proofs = [
            intent.move_evidence
            for intent in overlapping
            if intent.move_evidence is not None
        ]
        if isinstance(command.event, WatcherMoveEvent):
            proofs.append(
                ReconcileMoveEvidence(
                    command.event.source_path,
                    command.event.destination_path,
                    command.event.entry_type,
                )
            )
        distinct: list[ReconcileMoveEvidence] = []
        for proof in proofs:
            if proof not in distinct:
                distinct.append(proof)
        return distinct[0] if len(distinct) == 1 else None

    @staticmethod
    def _record_explicit_modify(
        uow: WatcherUnitOfWork,
        modification: ExplicitSourceModify | None,
        *,
        observed_at: datetime,
    ) -> None:
        if modification is None:
            return
        outcome = uow.content_observations.mark_explicit_modify(
            modification,
            observed_at=observed_at,
        )
        if outcome is not None and outcome.work_available:
            append_content_available(
                uow.outbox,
                library_id=modification.library_id,
                reason=ContentWakeReason.SOURCE_OBSERVED,
            )

    def _force_full_scan(
        self,
        uow: WatcherUnitOfWork,
        state: WatcherState,
        reason: FullRescanReason,
        observed_at: datetime,
        *,
        modification: ExplicitSourceModify | None,
    ) -> WatcherIngestResult:
        transition = uow.watcher.force_full_rescan(
            state.library_id,
            expected_latest_sequence=state.latest_sequence,
            reason=reason,
            observed_at=observed_at,
        )
        if transition is None:
            raise WatcherStale()
        self._record_explicit_modify(uow, modification, observed_at=observed_at)
        if transition.newly_required:
            _append_full_scan_required(uow, transition=transition)
        uow.commit()
        return WatcherIngestResult(
            sequence=transition.state.latest_sequence,
            disposition=WatcherIngestDisposition.FULL_SCAN_REQUIRED,
            intent_id=None,
            full_rescan_reason=transition.state.full_rescan_reason,
        )


__all__ = ["RecordWatcherEvent"]
