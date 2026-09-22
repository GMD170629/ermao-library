"""Durable, independently authorized MCP attachment transfers."""

import base64
import binascii
import re
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Protocol

from app.contracts.automation_upload import (
    UploadActor,
    UploadError,
    UploadOutcome,
    UploadPublication,
    UploadSpec,
    UploadTarget,
)
from app.contracts.diagnostics import FailureDiagnostics
from app.modules.automation.application.execution import RecheckMutationAccess
from app.modules.automation.application.receipts import (
    ReceiptStore,
    request_fingerprint,
)
from app.modules.automation.domain.access import EffectiveAccess, Scope

CHUNK_BYTES = 256 * 1024
BOOK_BYTES = 8 * 1024**3
COVER_BYTES = 12 * 1024**2
UPLOAD_COUNT = 20
LIFETIME_MS = 24 * 60 * 60 * 1000
TRANSFER_STATES = frozenset({"RECEIVING", "UPLOADED", "PUBLISHING"})
TERMINAL_STATES = frozenset(
    {"COMPLETED", "FAILED", "CANCELLED", "EXPIRED", "RECOVERY_REQUIRED"}
)


@dataclass(frozen=True)
class UploadRecord:
    id: str
    user_id: str
    grant_id: str
    spec: UploadSpec
    target: UploadTarget
    created_at_ms: int
    expires_at_ms: int
    offset: int = 0
    status: str = "RECEIVING"
    publication: UploadPublication | None = None
    outcome: UploadOutcome | None = None
    error_code: str | None = None
    staging_cleaned: bool = False
    file_saved: bool = False
    execution_version: int = 1


class UploadStore(Protocol):
    def get(self, upload_id: str, user_id: str, grant_id: str) -> UploadRecord: ...
    def save(self, record: UploadRecord) -> None: ...
    def capacity(self, grant_id: str) -> tuple[int, int]: ...
    def expired(self, now_ms: int) -> tuple[UploadRecord, ...]: ...
    def mark_cleaned(self, record: UploadRecord) -> None: ...
    def defer_cleanup(self, upload_id: str, until_ms: int) -> None: ...


class UploadFiles(Protocol):
    def lock(self, upload_id: str) -> AbstractContextManager[None]: ...
    def append(
        self, upload_id: str, confirmed: int, offset: int, data: bytes
    ) -> int: ...
    def verify(self, upload_id: str, size: int, digest: str) -> Path: ...
    def remove(self, upload_id: str) -> None: ...


class UploadGateway(Protocol):
    def target(self, actor: UploadActor, spec: UploadSpec) -> UploadTarget: ...
    def prepare(
        self, upload_id: str, spec: UploadSpec, target: UploadTarget, source: Path
    ) -> UploadPublication: ...
    def publish(self, publication: UploadPublication) -> None: ...
    def discard(
        self,
        upload_id: str,
        target: UploadTarget,
        publication: UploadPublication | None,
    ) -> None: ...
    def register(
        self, actor: UploadActor, spec: UploadSpec, publication: UploadPublication
    ) -> UploadOutcome: ...
    def progress(
        self, spec: UploadSpec, target: UploadTarget, outcome: UploadOutcome
    ) -> UploadOutcome: ...


class UploadUnitOfWork(Protocol):
    def commit(self) -> None: ...
    def rollback(self) -> None: ...


@dataclass(frozen=True)
class AutomationUploads:
    store: UploadStore
    files: UploadFiles
    books: UploadGateway
    covers: UploadGateway
    receipts: ReceiptStore
    authorize: RecheckMutationAccess
    uow: UploadUnitOfWork
    clock_ms: Callable[[], int]
    new_id: Callable[[], str]
    diagnostics: FailureDiagnostics

    def _gateway(self, spec: UploadSpec) -> UploadGateway:
        return self.books if spec.purpose != "cover" else self.covers

    def _actor(
        self, access: EffectiveAccess, spec: UploadSpec, *, current: bool = True
    ) -> UploadActor:
        scope = (
            Scope.FILES_MODIFY
            if spec.purpose == "replace"
            else Scope.FILES_UPLOAD
            if spec.purpose == "book"
            else Scope.BOOKS_WRITE
        )
        access = self.authorize.require(access, scope) if current else access
        access.require(scope)
        if spec.override:
            access.require(Scope.BOOKS_WRITE)
        return UploadActor(
            access.user_id,
            access.grant_id,
            access.permissions.library_ids,
            Scope.BOOKS_WRITE in access.permissions.scopes,
        )

    def _current_actor(
        self, access: EffectiveAccess, record: UploadRecord
    ) -> UploadActor:
        actor = self._actor(access, record.spec)
        if record.target.library_id not in actor.library_ids:
            raise UploadError("RESOURCE_NOT_FOUND")
        return actor

    def _owned(self, access: EffectiveAccess, upload_id: str) -> UploadRecord:
        record = self.store.get(upload_id, access.user_id, access.grant_id)
        actor = self._actor(access, record.spec, current=False)
        if record.target.library_id not in actor.library_ids:
            raise UploadError("RESOURCE_NOT_FOUND")
        return record

    @staticmethod
    def view(record: UploadRecord) -> dict[str, object]:
        return {
            "upload_id": record.id,
            "operation_id": record.id,
            "kind": "file_replace"
            if record.spec.purpose == "replace"
            else "book_upload"
            if record.spec.purpose == "book"
            else "cover_upload",
            "status": record.status,
            "library_id": record.target.library_id,
            "relative_path": record.target.relative_path
            if record.spec.purpose != "cover"
            else record.spec.filename,
            "received_bytes": record.offset,
            "size_bytes": record.spec.size_bytes,
            "sha256": record.spec.sha256,
            "expires_at_ms": record.expires_at_ms,
            "chunk_bytes": CHUNK_BYTES,
            "file_saved": record.file_saved,
            "error_code": record.error_code,
            "result": asdict(record.outcome) if record.outcome else None,
        }

    def begin_upload(
        self, access: EffectiveAccess, spec: UploadSpec, request_id: str
    ) -> dict[str, object]:
        if (
            not spec.filename
            or len(spec.filename) > 255
            or spec.filename in {".", ".."}
            or any(ord(c) < 32 or c in "/\\" for c in spec.filename)
            or not re.fullmatch(r"[a-fA-F0-9]{64}", spec.sha256)
            or not 0
            < spec.size_bytes
            <= (BOOK_BYTES if spec.purpose != "cover" else COVER_BYTES)
        ):
            raise UploadError("INVALID_UPLOAD")
        if spec.purpose == "replace":
            if (
                not spec.library_id
                or not spec.source_node_id
                or not spec.expected_source_version
                or spec.book_id
                or spec.override
                or spec.directory_node_id
                or spec.expected_revision
            ):
                raise UploadError("INVALID_UPLOAD_TARGET")
        elif spec.purpose == "book":
            if (
                spec.source_node_id
                or spec.expected_source_version
                or not spec.library_id
                or spec.book_id
                or spec.expected_revision
                or spec.override
            ):
                raise UploadError("INVALID_UPLOAD_TARGET")
        elif (
            spec.source_node_id
            or spec.expected_source_version
            or not spec.book_id
            or not spec.expected_revision
            or spec.library_id
            or spec.directory_node_id
        ):
            raise UploadError("INVALID_UPLOAD_TARGET")
        spec = replace(spec, sha256=spec.sha256.lower())
        fingerprint = request_fingerprint("begin_upload", asdict(spec), request_id)
        actor = self._actor(access, spec)
        previous = self.receipts.lookup(
            access.grant_id, request_id, "begin_upload", fingerprint
        )
        if previous:
            return self.progress(access, str(previous["upload_id"]))
        target = self._gateway(spec).target(actor, spec)
        self.uow.rollback()
        now = self.clock_ms()
        step = "claim_receipt"
        try:
            previous = self.receipts.claim(
                access.grant_id, request_id, "begin_upload", fingerprint, now
            )
            if previous:
                self.uow.rollback()
                return self.progress(access, str(previous["upload_id"]))
            actor = self._actor(access, spec)
            if target.library_id not in actor.library_ids:
                raise UploadError("RESOURCE_NOT_FOUND")
            count, size = self.store.capacity(access.grant_id)
            if count >= UPLOAD_COUNT or size + spec.size_bytes > BOOK_BYTES:
                raise UploadError("UPLOAD_QUOTA_EXCEEDED")
            record = UploadRecord(
                self.new_id(),
                access.user_id,
                access.grant_id,
                spec,
                target,
                now,
                now + LIFETIME_MS,
                execution_version=2,
            )
            step = "save_state"
            self.store.save(record)
            self.receipts.complete(
                access.grant_id, request_id, {"upload_id": record.id}
            )
            step = "commit"
            self.uow.commit()
            return self.view(record)
        except Exception as error:
            diagnostic = self.diagnostics.prepare(
                error,
                event="upload.begin_failed",
                context={"request_id": request_id, "step": step},
            )
            try:
                self.uow.rollback()
            except Exception as rollback_error:
                secondary = self.diagnostics.prepare(
                    rollback_error,
                    event="upload.rollback_failed",
                    context={
                        "request_id": request_id,
                        "step": "rollback",
                        "parent_diagnostic_id": diagnostic.diagnostic_id,
                    },
                )
                self.diagnostics.persist(secondary)
                raise
            finally:
                self.diagnostics.persist(diagnostic)
            raise

    def chunk(
        self, access: EffectiveAccess, upload_id: str, offset: int, encoded: str
    ) -> dict[str, object]:
        if len(encoded) > (CHUNK_BYTES + 2) // 3 * 4:
            raise UploadError("CHUNK_TOO_LARGE")
        try:
            data = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as error:
            raise UploadError("INVALID_BASE64") from error
        if not data or len(data) > CHUNK_BYTES or offset < 0:
            raise UploadError("INVALID_CHUNK")
        self._owned(access, upload_id)
        self.uow.rollback()
        with self.files.lock(upload_id):
            record = self._owned(access, upload_id)
            self._current_actor(access, record)
            if record.status not in {"RECEIVING", "UPLOADED"}:
                raise UploadError("UPLOAD_NOT_RECEIVING")
            if record.expires_at_ms <= self.clock_ms():
                raise UploadError("UPLOAD_EXPIRED")
            if offset + len(data) > record.spec.size_bytes:
                raise UploadError("UPLOAD_SIZE_MISMATCH")
            self.uow.rollback()
            confirmed = self.files.append(upload_id, record.offset, offset, data)
            record = replace(
                record,
                offset=confirmed,
                expires_at_ms=self.clock_ms() + LIFETIME_MS,
                status="UPLOADED"
                if confirmed == record.spec.size_bytes
                else "RECEIVING",
            )
            self._current_actor(access, record)
            self.store.save(record)
            self.uow.commit()
            return self.view(record)

    def complete(self, access: EffectiveAccess, upload_id: str) -> dict[str, object]:
        self._owned(access, upload_id)
        self.uow.rollback()
        with self.files.lock(upload_id):
            record = self._owned(access, upload_id)
            actor = self._current_actor(access, record)
            if (
                record.status == "RECOVERY_REQUIRED"
                and record.spec.purpose != "cover"
                and record.execution_version == 2
                and record.file_saved
            ):
                record = replace(
                    record,
                    status="SAVED",
                    error_code=None,
                )
            if record.status in TERMINAL_STATES or record.status in {
                "QUEUED",
                "IMPORTING",
            }:
                return self.progress(access, upload_id)
            if (
                record.status in {"RECEIVING", "UPLOADED"}
                and record.expires_at_ms <= self.clock_ms()
            ):
                raise UploadError("UPLOAD_EXPIRED")
            if record.offset != record.spec.size_bytes:
                raise UploadError("UPLOAD_INCOMPLETE")
            gateway = self._gateway(record.spec)
            step = "validate_target"
            try:
                if record.spec.purpose != "cover":
                    if record.execution_version != 2 or (
                        record.publication is not None
                        and record.publication.execution_version != 2
                    ):
                        raise UploadError("UPLOAD_PLAN_REQUIRES_REFRESH")
                    if record.status == "PUBLISHING":
                        # A restart cannot establish whether the file operation ran.
                        # Retain its files and journal instead of replaying publication.
                        raise UploadError("UPLOAD_PUBLICATION_INTERRUPTED")
                if record.publication is None:
                    target = gateway.target(actor, record.spec)
                    if target != record.target:
                        raise UploadError("UPLOAD_TARGET_CHANGED")
                    self.uow.rollback()
                    step = "verify_upload"
                    source = self.files.verify(
                        upload_id, record.spec.size_bytes, record.spec.sha256
                    )
                    step = "prepare_upload"
                    publication = gateway.prepare(
                        upload_id, record.spec, target, source
                    )
                    record = replace(
                        record, status="PUBLISHING", publication=publication
                    )
                    step = "save_state"
                    self.store.save(record)
                    step = "commit"
                    self.uow.commit()
                actor = self._current_actor(access, record)
                # A saved file needs only scan registration on a subsequent call.
                if record.spec.purpose != "replace" and not record.file_saved:
                    target = gateway.target(actor, record.spec)
                    if target != record.target:
                        raise UploadError("UPLOAD_TARGET_CHANGED")
                self.uow.rollback()
                if record.status == "PUBLISHING":
                    assert record.publication is not None
                    step = "publish_upload"
                    gateway.publish(record.publication)
                    record = replace(record, status="SAVED", file_saved=True)
                    step = "save_state"
                    self.store.save(record)
                    step = "commit"
                    self.uow.commit()
                actor = self._current_actor(access, record)
                assert record.publication is not None
                step = "register_upload"
                outcome = gateway.register(actor, record.spec, record.publication)
                record = replace(record, status=outcome.status, outcome=outcome)
                step = "save_state"
                self.store.save(record)
                step = "commit"
                self.uow.commit()
            except Exception as error:
                diagnostic = self.diagnostics.prepare(
                    error,
                    event="upload.complete_failed",
                    context={
                        "operation_id": upload_id,
                        "library_id": record.target.library_id,
                        "stage": record.status,
                        "step": step,
                    },
                )
                try:
                    self.uow.rollback()
                except Exception as rollback_error:
                    secondary = self.diagnostics.prepare(
                        rollback_error,
                        event="upload.rollback_failed",
                        context={
                            "operation_id": upload_id,
                            "step": "rollback",
                            "parent_diagnostic_id": diagnostic.diagnostic_id,
                        },
                    )
                    self.diagnostics.persist(secondary)
                    raise
                finally:
                    self.diagnostics.persist(diagnostic)
                if (
                    not isinstance(error, UploadError)
                    and record.spec.purpose == "cover"
                ):
                    raise
                if str(error) == "LIBRARY_BUSY":
                    record = replace(record, publication=None)
                record = replace(
                    record,
                    status="RECOVERY_REQUIRED"
                    if record.spec.purpose != "cover"
                    and record.publication is not None
                    else "FAILED",
                    error_code=str(error)
                    if isinstance(error, UploadError)
                    else "UPLOAD_PUBLICATION_INTERRUPTED"
                    if record.publication is not None
                    else "UPLOAD_SAVE_FAILED",
                )
                step = "save_state"
                self.store.save(record)
                step = "commit"
                self.uow.commit()
                if not isinstance(error, UploadError):
                    raise
                return self.view(record)
            finally:
                self.uow.rollback()
            self._gateway(record.spec).discard(
                record.id, record.target, record.publication
            )
            self.files.remove(upload_id)
            record = replace(record, staging_cleaned=True)
            step = "save_state"
            self.store.save(record)
            step = "commit"
            self.uow.commit()
            return self.view(record)

    def describe(self, access: EffectiveAccess, upload_id: str) -> UploadRecord:
        record = self._owned(access, upload_id)
        if record.status in {"QUEUED", "IMPORTING"}:
            assert record.outcome is not None
            outcome = self._gateway(record.spec).progress(
                record.spec, record.target, record.outcome
            )
            record = replace(
                record,
                status=outcome.status,
                outcome=outcome,
                error_code=outcome.error_code,
            )
        elif (
            record.status in {"RECEIVING", "UPLOADED"}
            and record.expires_at_ms <= self.clock_ms()
        ):
            record = replace(record, status="EXPIRED", error_code="UPLOAD_EXPIRED")
        return record

    def progress(self, access: EffectiveAccess, upload_id: str) -> dict[str, object]:
        return self.view(self.describe(access, upload_id))

    def cancel(self, access: EffectiveAccess, upload_id: str) -> dict[str, object]:
        self._owned(access, upload_id)
        self.uow.rollback()
        with self.files.lock(upload_id):
            record = self._owned(access, upload_id)
            if record.status == "CANCELLED":
                return self.view(record)
            if record.status not in {"RECEIVING", "UPLOADED"}:
                raise UploadError("UPLOAD_ALREADY_SUBMITTED")
            record = replace(record, status="CANCELLED")
            self.store.save(record)
            self.uow.commit()
            self._gateway(record.spec).discard(
                record.id, record.target, record.publication
            )
            self.files.remove(upload_id)
            record = replace(record, staging_cleaned=True)
            self.store.save(record)
            self.uow.commit()
            return self.view(record)

    def cleanup(self) -> None:
        records = self.store.expired(self.clock_ms())
        self.uow.rollback()
        for candidate in records:
            step = "lock_upload"
            try:
                with self.files.lock(candidate.id):
                    record = self.store.get(
                        candidate.id, candidate.user_id, candidate.grant_id
                    )
                    if record.staging_cleaned or record.expires_at_ms > self.clock_ms():
                        continue
                    if (
                        record.spec.purpose != "cover"
                        and record.publication is not None
                        and (
                            record.execution_version != 2
                            or record.publication.execution_version != 2
                            or not record.file_saved
                        )
                    ):
                        self.store.defer_cleanup(
                            candidate.id, self.clock_ms() + LIFETIME_MS
                        )
                        step = "commit"
                        self.uow.commit()
                        continue
                    if record.status in TRANSFER_STATES or record.status == "SAVED":
                        record = replace(
                            record, status="EXPIRED", error_code="UPLOAD_EXPIRED"
                        )
                        step = "save_state"
                        self.store.save(record)
                        step = "commit"
                        self.uow.commit()
                    self.uow.rollback()
                    step = "discard_staging"
                    self._gateway(record.spec).discard(
                        record.id, record.target, record.publication
                    )
                    step = "remove_staging"
                    self.files.remove(record.id)
                    self.store.mark_cleaned(record)
                    step = "commit"
                    self.uow.commit()
            except Exception as error:
                diagnostic = self.diagnostics.prepare(
                    error,
                    event="upload.cleanup_failed",
                    context={
                        "operation_id": candidate.id,
                        "library_id": candidate.target.library_id,
                        "stage": candidate.status,
                        "step": step,
                    },
                )
                try:
                    self.uow.rollback()
                except Exception as rollback_error:
                    secondary = self.diagnostics.prepare(
                        rollback_error,
                        event="upload.cleanup_rollback_failed",
                        context={
                            "operation_id": candidate.id,
                            "step": "rollback",
                            "parent_diagnostic_id": diagnostic.diagnostic_id,
                        },
                    )
                    self.diagnostics.persist(secondary)
                    raise
                finally:
                    self.diagnostics.persist(diagnostic)
                if not isinstance(error, (UploadError, OSError)):
                    raise
                # Retain uncertain staging, but do not let 20 such rows starve cleanup.
                self.store.defer_cleanup(candidate.id, self.clock_ms() + 5 * 60 * 1000)
                step = "commit"
                self.uow.commit()
            finally:
                self.uow.rollback()
