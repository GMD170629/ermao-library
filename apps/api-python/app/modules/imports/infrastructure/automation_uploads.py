"""Import upload target validation and existing queue integration."""

import hashlib
import os
import stat
from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.automation_upload import (
    UploadActor,
    UploadError,
    UploadOutcome,
    UploadPublication,
    UploadSpec,
    UploadTarget,
)
from app.core.config import Settings
from app.infrastructure.file_identity import file_identity
from app.models import (
    Library,
    LibraryBookMetadata,
    LibraryImportTask,
    LibraryReadableResource,
    LibraryResourceAsset,
    LibrarySourceNode,
)
from app.modules.imports.domain.scan_policy import MissingEntryPolicy, ScanScope
from app.modules.imports.infrastructure.readable_resource.task_queue import (
    SqlAlchemyLibraryImportTaskQueue,
)
from app.modules.imports.infrastructure.uploaded_file_publication import (
    AtomicUploadedFilePublisher,
)
from app.modules.imports.public import (
    is_supported_import_filename,
    safe_upload_filename,
)
from app.services.audio_metadata import is_supported_audio_file
from app.services.import_preferences import (
    extension_is_allowed,
    load_raw_import_preferences_projection,
    matches_ignore_patterns,
    prepare_import_preferences,
)


class ImportAttachmentUploads:
    def __init__(
        self,
        db: Session,
        settings: Settings,
        open_directory: Callable[[Path, str], AbstractContextManager[int]],
    ) -> None:
        self.db, self.settings, self.directories = db, settings, open_directory
        self.publisher = AtomicUploadedFilePublisher(open_directory=open_directory)

    def target(self, actor: UploadActor, spec: UploadSpec) -> UploadTarget:
        if spec.library_id not in actor.library_ids:
            raise UploadError("RESOURCE_NOT_FOUND")
        library = self.db.scalar(
            select(Library)
            .where(Library.id == spec.library_id, Library.enabled.is_(True))
            .execution_options(populate_existing=True)
        )
        if library is None:
            raise UploadError("RESOURCE_NOT_FOUND")
        parent = ""
        original = None
        if spec.purpose == "replace":
            node = self.db.scalar(
                select(LibrarySourceNode).where(
                    LibrarySourceNode.id == spec.source_node_id,
                    LibrarySourceNode.library_id == library.id,
                    LibrarySourceNode.physical_kind == "REGULAR_FILE",
                )
            )
            if node is None or spec.filename != node.relative_path.rpartition("/")[2]:
                raise UploadError("RESOURCE_NOT_FOUND")
            parent = node.relative_path.rpartition("/")[0]
            with self.directories(Path(library.root_path), parent) as directory:
                observed_source = os.stat(
                    spec.filename, dir_fd=directory, follow_symlinks=False
                )
                original = file_identity(observed_source)
                version = hashlib.sha256(
                    f"{original.size}:{original.mtime_ns}".encode()
                ).hexdigest()
                if (
                    version != spec.expected_source_version
                    or not stat.S_ISREG(original.mode)
                    or original.link_count != 1
                ):
                    raise UploadError("SOURCE_CHANGED")
        elif spec.directory_node_id:
            node = self.db.scalar(
                select(LibrarySourceNode)
                .where(
                    LibrarySourceNode.id == spec.directory_node_id,
                    LibrarySourceNode.library_id == library.id,
                    LibrarySourceNode.physical_kind == "DIRECTORY",
                )
                .execution_options(populate_existing=True)
            )
            if node is None:
                raise UploadError("RESOURCE_NOT_FOUND")
            parent = node.relative_path
        root, library_id = Path(library.root_path), library.id
        preferences = prepare_import_preferences(
            load_raw_import_preferences_projection(self.db)
        )
        if safe_upload_filename(
            spec.filename
        ) != spec.filename or not is_supported_import_filename(spec.filename):
            raise UploadError("UNSUPPORTED_UPLOAD_FILENAME")
        path = root / parent / spec.filename
        if not extension_is_allowed(path, preferences) or matches_ignore_patterns(
            path, preferences.ignore_patterns
        ):
            raise UploadError("UPLOAD_EXCLUDED")
        if is_supported_audio_file(spec.filename) and spec.size_bytes > min(
            self.settings.audiobook_max_file_bytes,
            self.settings.audiobook_max_bundle_bytes,
        ):
            raise UploadError("UPLOAD_TOO_LARGE")
        try:
            with self.directories(root, parent) as descriptor:
                observed = os.fstat(descriptor)
                if not os.access(".", os.W_OK, dir_fd=descriptor):
                    raise UploadError("UPLOAD_TARGET_READ_ONLY")
        except (OSError, ValueError) as error:
            if isinstance(error, UploadError):
                raise
            raise UploadError("UPLOAD_TARGET_UNAVAILABLE") from error
        return UploadTarget(
            library_id,
            root,
            f"{parent}/{spec.filename}" if parent else spec.filename,
            observed.st_dev,
            observed.st_ino,
            original,
        )

    def prepare(
        self, upload_id: str, spec: UploadSpec, target: UploadTarget, source: Path
    ) -> UploadPublication:
        return self.publisher.prepare_strict(
            upload_id, target, source, spec.size_bytes
        )

    def publish(self, publication: UploadPublication) -> None:
        target = publication.target
        library = self.db.get(Library, target.library_id, populate_existing=True)
        if (
            library is None
            or not library.enabled
            or Path(library.root_path) != target.root
        ):
            raise UploadError("UPLOAD_TARGET_CHANGED")
        if target.original is not None:
            node = self.db.scalar(
                select(LibrarySourceNode)
                .where(
                    LibrarySourceNode.library_id == target.library_id,
                    LibrarySourceNode.relative_path == target.relative_path,
                )
                .execution_options(populate_existing=True)
            )
            if node is None:
                raise UploadError("SOURCE_CHANGED")
        self.publisher.publish_strict(publication)

    def discard(
        self,
        upload_id: str,
        target: UploadTarget,
        publication: UploadPublication | None,
    ) -> None:
        try:
            parent = target.relative_path.rpartition("/")[0]
            with self.directories(target.root, parent) as directory:
                info = os.fstat(directory)
                if (info.st_dev, info.st_ino) != (
                    target.parent_device,
                    target.parent_inode,
                ):
                    raise UploadError("UPLOAD_TARGET_CHANGED")
                try:
                    os.unlink(f".upload-{upload_id}.part", dir_fd=directory)
                except FileNotFoundError:
                    # diagnostics-control-flow: staging cleanup is idempotent after publication or earlier cleanup.
                    pass
        except ValueError as error:
            if isinstance(error, UploadError):
                raise
            raise UploadError("UPLOAD_TARGET_UNAVAILABLE") from error

    def register(
        self, actor: UploadActor, spec: UploadSpec, publication: UploadPublication
    ) -> UploadOutcome:
        target = publication.target
        if target.library_id not in actor.library_ids:
            raise UploadError("RESOURCE_NOT_FOUND")
        parent = target.relative_path.rpartition("/")[0]
        task, _ = SqlAlchemyLibraryImportTaskQueue(self.db).request_library_scan(
            target.library_id,
            missing_entry_policy=MissingEntryPolicy.PRESERVE,
            scan_scopes=(ScanScope(relative_path=parent, recursive=False),),
        )
        return UploadOutcome("QUEUED", task_id=task.id)

    def progress(
        self, spec: UploadSpec, target: UploadTarget, outcome: UploadOutcome
    ) -> UploadOutcome:
        task = (
            self.db.get(LibraryImportTask, outcome.task_id) if outcome.task_id else None
        )
        if task and task.state in {"QUEUED", "RUNNING"}:
            return UploadOutcome(
                "QUEUED" if task.state == "QUEUED" else "IMPORTING",
                task_id=outcome.task_id,
            )
        rows = self.db.execute(
            select(LibraryReadableResource, LibraryResourceAsset)
            .join(
                LibraryResourceAsset,
                LibraryResourceAsset.resource_id == LibraryReadableResource.id,
            )
            .join(
                LibrarySourceNode,
                LibrarySourceNode.id == LibraryResourceAsset.source_node_id,
            )
            .where(
                LibrarySourceNode.library_id == target.library_id,
                LibrarySourceNode.relative_path == target.relative_path,
            )
        ).all()
        if not rows:
            # A bounded directory scan can enqueue continuation before observing
            # this filename. Absence is final only after that input is complete.
            continuation = self.db.scalar(
                select(LibraryImportTask.id)
                .join(
                    LibrarySourceNode,
                    LibrarySourceNode.id == LibraryImportTask.source_node_id,
                )
                .where(
                    LibraryImportTask.library_id == target.library_id,
                    LibraryImportTask.kind == "CONTINUE_SOURCE",
                    LibraryImportTask.state.in_(("QUEUED", "RUNNING")),
                    LibrarySourceNode.relative_path
                    == target.relative_path.rpartition("/")[0],
                )
                .limit(1)
            )
            if continuation:
                return UploadOutcome("IMPORTING", task_id=outcome.task_id)
            return UploadOutcome(
                "FAILED", task_id=outcome.task_id, error_code="UPLOAD_NOT_RECOGNIZED"
            )
        if any(
            asset.import_state == "FAILED" or resource.import_state == "FAILED"
            for resource, asset in rows
        ):
            return UploadOutcome(
                "FAILED", task_id=outcome.task_id, error_code="UPLOAD_IMPORT_FAILED"
            )
        book_ids = tuple({resource.book_id for resource, _ in rows})
        active = self.db.scalar(
            select(LibraryImportTask.id)
            .where(
                LibraryImportTask.book_id.in_(book_ids),
                LibraryImportTask.kind == "IMPORT_BOOK",
                LibraryImportTask.state.in_(("QUEUED", "RUNNING")),
                LibraryImportTask.created_at >= task.created_at,
            )
            .limit(1)
        ) if task is not None else None
        pending = self.db.scalar(
            select(LibraryBookMetadata.book_id)
            .where(
                LibraryBookMetadata.book_id.in_(book_ids),
                LibraryBookMetadata.metadata_pending.is_(True),
            )
            .limit(1)
        )
        failed_metadata = self.db.scalar(
            select(LibraryBookMetadata.book_id)
            .where(
                LibraryBookMetadata.book_id.in_(book_ids),
                LibraryBookMetadata.metadata_state == "FAILED",
            )
            .limit(1)
        )
        if failed_metadata is not None and active is None:
            return UploadOutcome(
                "FAILED", task_id=outcome.task_id, error_code="UPLOAD_IMPORT_FAILED"
            )
        complete = (
            pending is None
            and active is None
            and all(
                resource.import_state == "READY" and asset.import_state == "READY"
                for resource, asset in rows
            )
        )
        if not complete and task and task.state == "FAILED":
            return UploadOutcome(
                "FAILED", task_id=outcome.task_id, error_code="UPLOAD_IMPORT_FAILED"
            )
        return UploadOutcome(
            "COMPLETED" if complete else "IMPORTING",
            task_id=outcome.task_id,
            book_ids=tuple(sorted({r.book_id for r, _ in rows})),
            resource_ids=tuple(sorted({r.id for r, _ in rows})),
        )
