"""Dormant PR6A workers for required original-source content."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.modules.catalog.application.content_dto import (
    ContentRunDisposition,
    RequiredManifestActivationOutcome,
    RequiredManifestStageBatch,
    RequiredOpeningDisposition,
    RequiredOpeningEvidence,
    RequiredOpeningProgress,
    RequiredOpeningRequest,
    RunContentTopologyProjectionResult,
    RunNextContentTopologyProjectionCommand,
    RunNextRequiredManifestCommand,
    RunNextRequiredOpeningCommand,
    RunNextSourceDigestCommand,
    RunRequiredManifestResult,
    RunRequiredOpeningResult,
    RunSourceDigestResult,
    SourceContentWorkFence,
    SourceDigestEvidence,
    SourceDigestProgress,
    SourceDigestWork,
    VolumeProcessingFact,
    VolumeProcessingWorkFence,
)
from app.modules.catalog.application.content_events import (
    ContentWakeReason,
    append_content_available,
)
from app.modules.catalog.application.content_ports import (
    ContentLeaseLost,
    ContentStale,
    ContentUnitOfWork,
    ContentUowFactory,
    RequiredOpeningCheckpointPort,
    RequiredOpeningOperationalError,
    RequiredOpeningPort,
    SourceDigestCheckpointPort,
    SourceDigestOperationalError,
    SourceDigestPort,
)
from app.modules.catalog.application.ports import (
    Clock,
    IdGenerator,
    OutboxEvent,
)
from app.modules.catalog.application.scan_ports import MonotonicClock
from app.modules.catalog.domain.content import (
    ContentProcessorKind,
    required_manifest_revision_impact,
)
from app.modules.catalog.domain.library import LibraryControlState

_CHECKPOINT_SECONDS = 0.25
_MAX_CHECKPOINT_BYTES = 1024 * 1024
_MAX_TOPOLOGY_PROJECTION_VOLUMES = 500


def _active(uow: ContentUnitOfWork, library_id: str) -> bool:
    library = uow.libraries.get_for_content_for_update(library_id)
    return library is not None and library.control_state is LibraryControlState.ACTIVE


def _lease_deadline(now: datetime, lease_seconds: int) -> datetime:
    return now + timedelta(seconds=lease_seconds)


def _append_worker_event(
    uow: ContentUnitOfWork,
    *,
    event_type: str,
    library_id: str,
    target_name: str,
    target_id: str,
    outcome: str,
) -> None:
    uow.outbox.append(
        OutboxEvent(
            event_type,
            library_id,
            "SYSTEM",
            ((target_name, target_id), ("outcome", outcome)),
        )
    )


class RunNextContentTopologyProjection:
    """Project one bounded topology-to-content batch without a worker lease."""

    def __init__(
        self,
        *,
        unit_of_work_factory: ContentUowFactory,
        clock: Clock,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._clock = clock

    def execute(
        self,
        command: RunNextContentTopologyProjectionCommand,
    ) -> RunContentTopologyProjectionResult:
        now = self._clock.now()
        with self._unit_of_work_factory() as uow:
            if not _active(uow, command.library_id):
                return RunContentTopologyProjectionResult(
                    ContentRunDisposition.LIBRARY_NOT_ACTIVE,
                    0,
                    False,
                )
            outcome = uow.topology_projection.project_next_batch(
                command.library_id,
                limit=_MAX_TOPOLOGY_PROJECTION_VOLUMES,
                projected_at=now,
            )
            if not outcome.projection_performed:
                return RunContentTopologyProjectionResult(
                    ContentRunDisposition.NO_WORK,
                    0,
                    False,
                )
            if outcome.work_remaining:
                append_content_available(
                    uow.outbox,
                    library_id=command.library_id,
                    reason=ContentWakeReason.TOPOLOGY_ACTIVATED,
                )
            uow.commit()
            return RunContentTopologyProjectionResult(
                ContentRunDisposition.COMPLETED,
                outcome.processed_volume_count,
                outcome.work_remaining,
            )


class _DigestCheckpoint(SourceDigestCheckpointPort):
    def __init__(
        self,
        *,
        unit_of_work_factory: ContentUowFactory,
        clock: Clock,
        monotonic_clock: MonotonicClock,
        fence: SourceContentWorkFence,
        expected_size: int,
        lease_seconds: int,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._clock = clock
        self._monotonic_clock = monotonic_clock
        self._fence = fence
        self._expected_size = expected_size
        self._lease_seconds = lease_seconds
        self._last_bytes = 0
        self._poisoned = False
        self._next_check_at = monotonic_clock.seconds() + _CHECKPOINT_SECONDS

    @property
    def fence(self) -> SourceContentWorkFence:
        return self._fence

    def assert_not_poisoned(self) -> None:
        if self._poisoned:
            raise ContentStale()

    def checkpoint(self, progress: SourceDigestProgress) -> None:
        if self._poisoned:
            raise ContentStale()
        if (
            progress.source_entry_id != self._fence.source_entry_id
            or progress.input_revision != self._fence.input_revision
            or progress.bytes_hashed <= self._last_bytes
            or progress.bytes_hashed > self._expected_size
        ):
            self._poisoned = True
            raise ContentStale()
        monotonic_now = self._monotonic_clock.seconds()
        if monotonic_now >= self._next_check_at:
            now = self._clock.now()
            with self._unit_of_work_factory() as uow:
                if not _active(uow, self._fence.library_id):
                    self._poisoned = True
                    raise ContentLeaseLost()
                updated = uow.source_contents.heartbeat_digest(
                    self._fence,
                    now=now,
                    lease_expires_at=_lease_deadline(now, self._lease_seconds),
                )
                if updated is None:
                    self._poisoned = True
                    raise ContentLeaseLost()
                uow.commit()
                self._fence = updated
            self._next_check_at = monotonic_now + _CHECKPOINT_SECONDS
        self._last_bytes = progress.bytes_hashed


class _OpeningCheckpoint(RequiredOpeningCheckpointPort):
    def __init__(
        self,
        *,
        unit_of_work_factory: ContentUowFactory,
        clock: Clock,
        monotonic_clock: MonotonicClock,
        fence: VolumeProcessingWorkFence,
        request: RequiredOpeningRequest,
        lease_seconds: int,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._clock = clock
        self._monotonic_clock = monotonic_clock
        self._fence = fence
        self._request = request
        self._lease_seconds = lease_seconds
        self._last_bytes = 0
        self._last_sources = 0
        self._poisoned = False
        self._next_check_at = monotonic_clock.seconds() + _CHECKPOINT_SECONDS

    @property
    def fence(self) -> VolumeProcessingWorkFence:
        return self._fence

    def assert_terminal(self, evidence: RequiredOpeningEvidence) -> None:
        if not isinstance(evidence, RequiredOpeningEvidence):
            raise TypeError("opening port must return RequiredOpeningEvidence")
        if self._poisoned or (
            evidence.disposition is RequiredOpeningDisposition.READY
            and self._last_sources != len(self._request.sources)
        ):
            raise ContentStale()

    def checkpoint(self, progress: RequiredOpeningProgress) -> None:
        if self._poisoned:
            raise ContentStale()
        if not isinstance(progress, RequiredOpeningProgress):
            self._poisoned = True
            raise TypeError("opening checkpoint requires RequiredOpeningProgress")
        bytes_delta = progress.bytes_read - self._last_bytes
        sources_delta = progress.sources_completed - self._last_sources
        if (
            progress.volume_id != self._request.volume_id
            or progress.topology_unit_revision_id
            != self._request.topology_unit_revision_id
            or bytes_delta < 0
            or bytes_delta > _MAX_CHECKPOINT_BYTES
            or sources_delta not in {0, 1}
            or (bytes_delta == 0 and sources_delta == 0)
            or progress.sources_completed > len(self._request.sources)
        ):
            self._poisoned = True
            raise ContentStale()
        monotonic_now = self._monotonic_clock.seconds()
        if monotonic_now >= self._next_check_at:
            now = self._clock.now()
            with self._unit_of_work_factory() as uow:
                if not _active(uow, self._fence.library_id):
                    self._poisoned = True
                    raise ContentLeaseLost()
                updated = uow.processing.heartbeat(
                    self._fence,
                    now=now,
                    lease_expires_at=_lease_deadline(now, self._lease_seconds),
                )
                if updated is None:
                    self._poisoned = True
                    raise ContentLeaseLost()
                uow.commit()
                self._fence = updated.fence()
            self._next_check_at = monotonic_now + _CHECKPOINT_SECONDS
        self._last_bytes = progress.bytes_read
        self._last_sources = progress.sources_completed


class RunNextSourceDigest:
    def __init__(
        self,
        *,
        unit_of_work_factory: ContentUowFactory,
        digest_port: SourceDigestPort,
        clock: Clock,
        monotonic_clock: MonotonicClock,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._digest_port = digest_port
        self._clock = clock
        self._monotonic_clock = monotonic_clock

    def execute(self, command: RunNextSourceDigestCommand) -> RunSourceDigestResult:
        active, work = self._claim(command)
        if not active:
            return RunSourceDigestResult(
                ContentRunDisposition.LIBRARY_NOT_ACTIVE,
                None,
                None,
            )
        if work is None:
            return RunSourceDigestResult(ContentRunDisposition.NO_WORK, None, None)
        checkpoint = _DigestCheckpoint(
            unit_of_work_factory=self._unit_of_work_factory,
            clock=self._clock,
            monotonic_clock=self._monotonic_clock,
            fence=work.fence,
            expected_size=work.request.expected_stat.size_bytes,
            lease_seconds=command.lease_seconds,
        )
        try:
            evidence = self._digest_port.digest(work.request, checkpoint)
            checkpoint.assert_not_poisoned()
        except SourceDigestOperationalError as error:
            return self._release(
                checkpoint.fence,
                command,
                diagnostic_code=error.code,
            )
        except (ContentLeaseLost, ContentStale):
            return self._release_stale(checkpoint.fence, command)
        return self._publish(checkpoint.fence, evidence, command)

    def _claim(
        self, command: RunNextSourceDigestCommand
    ) -> tuple[bool, SourceDigestWork | None]:
        now = self._clock.now()
        with self._unit_of_work_factory() as uow:
            if not _active(uow, command.library_id):
                return False, None
            work = uow.source_contents.claim_next_digest(
                command.library_id,
                owner_token=command.owner_token,
                now=now,
                lease_expires_at=_lease_deadline(now, command.lease_seconds),
                defer_until=now + timedelta(seconds=command.retry_seconds),
            )
            if work.work is not None or work.deferred_count:
                uow.commit()
            return True, work.work

    def _publish(
        self,
        fence: SourceContentWorkFence,
        evidence: SourceDigestEvidence,
        command: RunNextSourceDigestCommand,
    ) -> RunSourceDigestResult:
        if not isinstance(evidence, SourceDigestEvidence):
            raise TypeError("digest port must return SourceDigestEvidence")
        now = self._clock.now()
        with self._unit_of_work_factory() as uow:
            if not _active(uow, command.library_id):
                released = uow.source_contents.release_digest_for_retry(
                    fence,
                    diagnostic_code="LIBRARY_NOT_ACTIVE",
                    retry_at=now + timedelta(seconds=command.retry_seconds),
                    released_at=now,
                )
                if released is None:
                    return RunSourceDigestResult(
                        ContentRunDisposition.STALE,
                        fence.source_entry_id,
                        None,
                    )
                uow.commit()
                return RunSourceDigestResult(
                    ContentRunDisposition.LIBRARY_NOT_ACTIVE,
                    None,
                    None,
                )
            renewed = uow.source_contents.heartbeat_digest(
                fence,
                now=now,
                lease_expires_at=_lease_deadline(now, command.lease_seconds),
            )
            if renewed is None:
                return RunSourceDigestResult(
                    ContentRunDisposition.STALE,
                    fence.source_entry_id,
                    None,
                )
            outcome = uow.source_contents.publish_digest(
                renewed,
                evidence,
                published_at=now,
            )
            if outcome is None:
                return RunSourceDigestResult(
                    ContentRunDisposition.STALE,
                    fence.source_entry_id,
                    None,
                )
            scheduling = uow.processing.schedule_required_manifest_for_digest(
                outcome,
                scheduled_at=now,
            )
            _append_worker_event(
                uow,
                event_type="CATALOG_SOURCE_DIGEST_READY",
                library_id=command.library_id,
                target_name="sourceEntryId",
                target_id=outcome.current.source_entry_id,
                outcome=outcome.disposition.value,
            )
            if scheduling.wake_required:
                append_content_available(
                    uow.outbox,
                    library_id=command.library_id,
                    reason=ContentWakeReason.SOURCE_DIGEST_READY,
                )
            uow.commit()
            return RunSourceDigestResult(
                ContentRunDisposition.COMPLETED,
                outcome.current.source_entry_id,
                outcome.disposition,
            )

    def _release(
        self,
        fence: SourceContentWorkFence,
        command: RunNextSourceDigestCommand,
        *,
        diagnostic_code: str,
    ) -> RunSourceDigestResult:
        now = self._clock.now()
        with self._unit_of_work_factory() as uow:
            released = uow.source_contents.release_digest_for_retry(
                fence,
                diagnostic_code=diagnostic_code,
                retry_at=now + timedelta(seconds=command.retry_seconds),
                released_at=now,
            )
            if released is None:
                return RunSourceDigestResult(
                    ContentRunDisposition.STALE,
                    fence.source_entry_id,
                    None,
                )
            _append_worker_event(
                uow,
                event_type="CATALOG_SOURCE_DIGEST_RETRY",
                library_id=command.library_id,
                target_name="sourceEntryId",
                target_id=fence.source_entry_id,
                outcome=diagnostic_code,
            )
            uow.commit()
            return RunSourceDigestResult(
                ContentRunDisposition.RETRY_SCHEDULED,
                fence.source_entry_id,
                None,
            )

    def _release_stale(
        self,
        fence: SourceContentWorkFence,
        command: RunNextSourceDigestCommand,
    ) -> RunSourceDigestResult:
        now = self._clock.now()
        with self._unit_of_work_factory() as uow:
            released = uow.source_contents.release_digest_for_retry(
                fence,
                diagnostic_code="DIGEST_WORK_STALE",
                retry_at=now + timedelta(seconds=command.retry_seconds),
                released_at=now,
            )
            if released is not None:
                uow.commit()
        return RunSourceDigestResult(
            ContentRunDisposition.STALE,
            fence.source_entry_id,
            None,
        )


class _ProcessingUseCase:
    def __init__(
        self,
        *,
        unit_of_work_factory: ContentUowFactory,
        clock: Clock,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._clock = clock

    def _claim(
        self,
        *,
        library_id: str,
        owner_token: str,
        lease_seconds: int,
        defer_seconds: int,
        processor_kind: ContentProcessorKind,
    ) -> tuple[bool, VolumeProcessingFact | None]:
        now = self._clock.now()
        with self._unit_of_work_factory() as uow:
            if not _active(uow, library_id):
                return False, None
            fact = uow.processing.claim_next(
                library_id,
                processor_kind,
                owner_token=owner_token,
                now=now,
                lease_expires_at=_lease_deadline(now, lease_seconds),
                defer_until=now + timedelta(seconds=defer_seconds),
            )
            if fact.work is not None or fact.deferred_count:
                uow.commit()
            return True, fact.work

    def _release_processing_in_uow(
        self,
        uow: ContentUnitOfWork,
        fence: VolumeProcessingWorkFence,
        *,
        retry_seconds: int,
        diagnostic_code: str,
        now: datetime,
    ) -> bool:
        released = uow.processing.release_for_retry(
            fence,
            diagnostic_code=diagnostic_code,
            retry_at=now + timedelta(seconds=retry_seconds),
            released_at=now,
        )
        if released is None:
            return False
        _append_worker_event(
            uow,
            event_type="CATALOG_CONTENT_PROCESSOR_RETRY",
            library_id=fence.library_id,
            target_name="volumeId",
            target_id=fence.volume_id,
            outcome=diagnostic_code,
        )
        uow.commit()
        return True

    def _release_processing(
        self,
        fence: VolumeProcessingWorkFence,
        *,
        retry_seconds: int,
        diagnostic_code: str,
    ) -> bool:
        now = self._clock.now()
        with self._unit_of_work_factory() as uow:
            return self._release_processing_in_uow(
                uow,
                fence,
                retry_seconds=retry_seconds,
                diagnostic_code=diagnostic_code,
                now=now,
            )


class RunNextRequiredManifest(_ProcessingUseCase):
    def __init__(
        self,
        *,
        unit_of_work_factory: ContentUowFactory,
        id_generator: IdGenerator,
        clock: Clock,
    ) -> None:
        super().__init__(unit_of_work_factory=unit_of_work_factory, clock=clock)
        self._id_generator = id_generator

    def execute(
        self, command: RunNextRequiredManifestCommand
    ) -> RunRequiredManifestResult:
        active_library, processing = self._claim(
            library_id=command.library_id,
            owner_token=command.owner_token,
            lease_seconds=command.lease_seconds,
            defer_seconds=command.retry_seconds,
            processor_kind=ContentProcessorKind.REQUIRED_MANIFEST,
        )
        if not active_library:
            return RunRequiredManifestResult(
                ContentRunDisposition.LIBRARY_NOT_ACTIVE, None, None
            )
        if processing is None:
            return RunRequiredManifestResult(ContentRunDisposition.NO_WORK, None, None)
        fence = processing.fence()
        now = self._clock.now()
        with self._unit_of_work_factory() as uow:
            if not _active(uow, command.library_id):
                return self._inactive_manifest_in_uow(uow, fence, command, now=now)
            renewed = uow.processing.heartbeat(
                fence,
                now=now,
                lease_expires_at=_lease_deadline(now, command.lease_seconds),
            )
            if renewed is None:
                return RunRequiredManifestResult(
                    ContentRunDisposition.STALE, fence.volume_id, None
                )
            fence = renewed.fence()
            candidate = uow.required_manifests.load_candidate(
                fence,
                manifest_id=self._id_generator.new_id(),
            )
            if candidate is None:
                released = uow.processing.release_for_retry(
                    fence,
                    diagnostic_code="REQUIRED_SOURCE_PENDING",
                    retry_at=now + timedelta(seconds=command.retry_seconds),
                    released_at=now,
                )
                if released is None:
                    return RunRequiredManifestResult(
                        ContentRunDisposition.STALE, fence.volume_id, None
                    )
                uow.commit()
                return RunRequiredManifestResult(
                    ContentRunDisposition.RETRY_SCHEDULED,
                    fence.volume_id,
                    None,
                )
            active = uow.required_manifests.get_active_for_update(
                command.library_id,
                fence.volume_id,
            )
            try:
                impact = required_manifest_revision_impact(
                    active.fingerprints if active is not None else None,
                    candidate.facts.fingerprints,
                    base_content_revision=candidate.base_revisions.content_revision,
                    base_required_manifest_revision=(
                        candidate.base_revisions.required_manifest_revision
                    ),
                )
            except (TypeError, ValueError) as error:
                raise ContentStale() from error
            if impact.reuse_active_manifest:
                outcome = uow.required_manifests.retarget_active(
                    fence,
                    candidate,
                    impact,
                    retargeted_at=now,
                )
                if outcome is None:
                    return RunRequiredManifestResult(
                        ContentRunDisposition.STALE, fence.volume_id, None
                    )
                return self._finish_manifest(
                    uow,
                    fence,
                    candidate.topology_unit_revision_id,
                    outcome,
                    now=now,
                )
            uow.required_manifests.abandon_incomplete(fence, abandoned_at=now)
            staging = uow.required_manifests.begin_staging(
                fence,
                candidate,
                impact,
                created_at=now,
            )
            if staging is None:
                return RunRequiredManifestResult(
                    ContentRunDisposition.STALE, fence.volume_id, None
                )
            uow.commit()

        assets = candidate.facts.assets
        for start in range(0, len(assets), 500):
            batch_assets = assets[start : start + 500]
            batch = RequiredManifestStageBatch(
                start,
                batch_assets,
                start + len(batch_assets) == len(assets),
            )
            now = self._clock.now()
            with self._unit_of_work_factory() as uow:
                if not _active(uow, command.library_id):
                    return self._inactive_manifest_in_uow(uow, fence, command, now=now)
                renewed = uow.processing.heartbeat(
                    fence,
                    now=now,
                    lease_expires_at=_lease_deadline(now, command.lease_seconds),
                )
                if renewed is None:
                    return RunRequiredManifestResult(
                        ContentRunDisposition.STALE, fence.volume_id, None
                    )
                fence = renewed.fence()
                updated_staging = uow.required_manifests.append_staging_batch(
                    fence,
                    staging,
                    batch,
                    staged_at=now,
                )
                if updated_staging is None:
                    return RunRequiredManifestResult(
                        ContentRunDisposition.STALE, fence.volume_id, None
                    )
                staging = updated_staging
                uow.commit()

        now = self._clock.now()
        with self._unit_of_work_factory() as uow:
            if not _active(uow, command.library_id):
                return self._inactive_manifest_in_uow(uow, fence, command, now=now)
            renewed = uow.processing.heartbeat(
                fence,
                now=now,
                lease_expires_at=_lease_deadline(now, command.lease_seconds),
            )
            if renewed is None:
                return RunRequiredManifestResult(
                    ContentRunDisposition.STALE, fence.volume_id, None
                )
            fence = renewed.fence()
            outcome = uow.required_manifests.activate_staging(
                fence,
                staging,
                impact,
                activated_at=now,
            )
            if outcome is None:
                return RunRequiredManifestResult(
                    ContentRunDisposition.STALE, fence.volume_id, None
                )
            return self._finish_manifest(
                uow,
                fence,
                candidate.topology_unit_revision_id,
                outcome,
                now=now,
            )

    def _inactive_manifest_in_uow(
        self,
        uow: ContentUnitOfWork,
        fence: VolumeProcessingWorkFence,
        command: RunNextRequiredManifestCommand,
        *,
        now: datetime,
    ) -> RunRequiredManifestResult:
        released = self._release_processing_in_uow(
            uow,
            fence,
            retry_seconds=command.retry_seconds,
            diagnostic_code="LIBRARY_NOT_ACTIVE",
            now=now,
        )
        return RunRequiredManifestResult(
            (
                ContentRunDisposition.LIBRARY_NOT_ACTIVE
                if released
                else ContentRunDisposition.STALE
            ),
            None if released else fence.volume_id,
            None,
        )

    def _finish_manifest(
        self,
        uow: ContentUnitOfWork,
        fence: VolumeProcessingWorkFence,
        topology_unit_revision_id: str,
        outcome: RequiredManifestActivationOutcome,
        *,
        now: datetime,
    ) -> RunRequiredManifestResult:
        if not isinstance(outcome, RequiredManifestActivationOutcome):
            raise TypeError("manifest repository returned an invalid outcome")
        scheduled = uow.processing.schedule_required_opening(
            fence,
            outcome,
            topology_unit_revision_id=topology_unit_revision_id,
            scheduled_at=now,
        )
        if scheduled is None:
            return RunRequiredManifestResult(
                ContentRunDisposition.STALE, fence.volume_id, None
            )
        _append_worker_event(
            uow,
            event_type="CATALOG_REQUIRED_MANIFEST_READY",
            library_id=fence.library_id,
            target_name="volumeId",
            target_id=fence.volume_id,
            outcome=outcome.disposition.value,
        )
        if scheduled.wake_required:
            append_content_available(
                uow.outbox,
                library_id=fence.library_id,
                reason=ContentWakeReason.REQUIRED_MANIFEST_READY,
            )
        uow.commit()
        return RunRequiredManifestResult(
            ContentRunDisposition.COMPLETED,
            fence.volume_id,
            outcome.disposition,
        )


class RunNextRequiredOpening(_ProcessingUseCase):
    def __init__(
        self,
        *,
        unit_of_work_factory: ContentUowFactory,
        opening_port: RequiredOpeningPort,
        clock: Clock,
        monotonic_clock: MonotonicClock,
    ) -> None:
        super().__init__(unit_of_work_factory=unit_of_work_factory, clock=clock)
        self._opening_port = opening_port
        self._monotonic_clock = monotonic_clock

    def execute(
        self, command: RunNextRequiredOpeningCommand
    ) -> RunRequiredOpeningResult:
        active_library, processing = self._claim(
            library_id=command.library_id,
            owner_token=command.owner_token,
            lease_seconds=command.lease_seconds,
            defer_seconds=command.retry_seconds,
            processor_kind=ContentProcessorKind.REQUIRED_OPENING,
        )
        if not active_library:
            return RunRequiredOpeningResult(
                ContentRunDisposition.LIBRARY_NOT_ACTIVE, None, None
            )
        if processing is None:
            return RunRequiredOpeningResult(ContentRunDisposition.NO_WORK, None, None)
        fence = processing.fence()
        now = self._clock.now()
        with self._unit_of_work_factory() as uow:
            if not _active(uow, command.library_id):
                return self._inactive_opening_in_uow(uow, fence, command, now=now)
            renewed = uow.processing.heartbeat(
                fence,
                now=now,
                lease_expires_at=_lease_deadline(now, command.lease_seconds),
            )
            if renewed is None:
                return RunRequiredOpeningResult(
                    ContentRunDisposition.STALE, fence.volume_id, None
                )
            fence = renewed.fence()
            request = uow.processing.load_required_opening_request(fence)
            if request is None:
                return self._retry_opening_in_uow(
                    uow,
                    fence,
                    command,
                    diagnostic_code="REQUIRED_MANIFEST_STALE",
                    now=now,
                )
            uow.commit()
        checkpoint = _OpeningCheckpoint(
            unit_of_work_factory=self._unit_of_work_factory,
            clock=self._clock,
            monotonic_clock=self._monotonic_clock,
            fence=fence,
            request=request,
            lease_seconds=command.lease_seconds,
        )
        try:
            evidence = self._opening_port.inspect(request, checkpoint)
            checkpoint.assert_terminal(evidence)
        except RequiredOpeningOperationalError as error:
            return self._retry_opening(
                checkpoint.fence,
                command,
                diagnostic_code=error.code,
            )
        except (ContentLeaseLost, ContentStale):
            return self._release_opening_stale(checkpoint.fence, command)
        fence = checkpoint.fence
        now = self._clock.now()
        with self._unit_of_work_factory() as uow:
            if not _active(uow, command.library_id):
                return self._inactive_opening_in_uow(uow, fence, command, now=now)
            renewed = uow.processing.heartbeat(
                fence,
                now=now,
                lease_expires_at=_lease_deadline(now, command.lease_seconds),
            )
            if renewed is None:
                return RunRequiredOpeningResult(
                    ContentRunDisposition.STALE, fence.volume_id, None
                )
            completed = uow.processing.complete_required_opening(
                renewed.fence(),
                evidence,
                completed_at=now,
            )
            if completed is None:
                return RunRequiredOpeningResult(
                    ContentRunDisposition.STALE, fence.volume_id, None
                )
            _append_worker_event(
                uow,
                event_type="CATALOG_REQUIRED_OPENING_COMPLETED",
                library_id=fence.library_id,
                target_name="volumeId",
                target_id=fence.volume_id,
                outcome=evidence.disposition.value,
            )
            uow.commit()
            return RunRequiredOpeningResult(
                ContentRunDisposition.COMPLETED,
                fence.volume_id,
                evidence.disposition,
            )

    def _release_opening_stale(
        self,
        fence: VolumeProcessingWorkFence,
        command: RunNextRequiredOpeningCommand,
    ) -> RunRequiredOpeningResult:
        now = self._clock.now()
        with self._unit_of_work_factory() as uow:
            released = uow.processing.release_for_retry(
                fence,
                diagnostic_code="OPENING_WORK_STALE",
                retry_at=now + timedelta(seconds=command.retry_seconds),
                released_at=now,
            )
            if released is not None:
                uow.commit()
        return RunRequiredOpeningResult(
            ContentRunDisposition.STALE,
            fence.volume_id,
            None,
        )

    def _retry_opening(
        self,
        fence: VolumeProcessingWorkFence,
        command: RunNextRequiredOpeningCommand,
        *,
        diagnostic_code: str,
    ) -> RunRequiredOpeningResult:
        released = self._release_processing(
            fence,
            retry_seconds=command.retry_seconds,
            diagnostic_code=diagnostic_code,
        )
        return RunRequiredOpeningResult(
            (
                ContentRunDisposition.RETRY_SCHEDULED
                if released
                else ContentRunDisposition.STALE
            ),
            fence.volume_id,
            None,
        )

    def _retry_opening_in_uow(
        self,
        uow: ContentUnitOfWork,
        fence: VolumeProcessingWorkFence,
        command: RunNextRequiredOpeningCommand,
        *,
        diagnostic_code: str,
        now: datetime,
    ) -> RunRequiredOpeningResult:
        released = self._release_processing_in_uow(
            uow,
            fence,
            retry_seconds=command.retry_seconds,
            diagnostic_code=diagnostic_code,
            now=now,
        )
        return RunRequiredOpeningResult(
            (
                ContentRunDisposition.RETRY_SCHEDULED
                if released
                else ContentRunDisposition.STALE
            ),
            fence.volume_id,
            None,
        )

    def _inactive_opening_in_uow(
        self,
        uow: ContentUnitOfWork,
        fence: VolumeProcessingWorkFence,
        command: RunNextRequiredOpeningCommand,
        *,
        now: datetime,
    ) -> RunRequiredOpeningResult:
        released = self._release_processing_in_uow(
            uow,
            fence,
            retry_seconds=command.retry_seconds,
            diagnostic_code="LIBRARY_NOT_ACTIVE",
            now=now,
        )
        return RunRequiredOpeningResult(
            (
                ContentRunDisposition.LIBRARY_NOT_ACTIVE
                if released
                else ContentRunDisposition.STALE
            ),
            None if released else fence.volume_id,
            None,
        )


__all__ = [
    "RunNextContentTopologyProjection",
    "RunNextRequiredManifest",
    "RunNextRequiredOpening",
    "RunNextSourceDigest",
]
