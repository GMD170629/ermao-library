"""Book cover attachment adapter, reusing validated publication and metadata owners."""

import hashlib
import os
from pathlib import Path
from urllib.parse import quote

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
from app.infrastructure.file_identity import file_identity
from app.models import Library
from app.modules.library.application.metadata_patches import (
    MetadataPatchActor,
    PreparedMetadataPatch,
)
from app.modules.library.application.source_node_commands import PreparedSourceNodeCover
from app.modules.library.application.uploaded_cover import require_uploaded_cover
from app.modules.library.domain.metadata_patch import MetadataPatchError
from app.modules.library.infrastructure.metadata_patches import (
    SqlAlchemyMetadataPatches,
)
from app.modules.library.infrastructure.source_file_access import open_library_directory
from app.modules.library.infrastructure.source_node_cover import (
    FilesystemSourceNodeCoverPublication,
)


class LibraryAttachmentCovers:
    def __init__(self, db: Session, storage_root: Path) -> None:
        self.db, self.root = db, storage_root
        self.metadata = SqlAlchemyMetadataPatches(db)
        self.publication = FilesystemSourceNodeCoverPublication(
            storage_root, max_bytes=12 * 1024**2
        )

    def target(self, actor: UploadActor, spec: UploadSpec) -> UploadTarget:
        snapshot = require_uploaded_cover(
            actor,
            spec,
            self.metadata.snapshot("book", spec.book_id or "", actor.library_ids),
        )
        library = self.db.scalar(
            select(Library).where(
                Library.id == snapshot.library_id, Library.enabled.is_(True)
            )
        )
        if library is None:
            raise UploadError("RESOURCE_NOT_FOUND")
        root, library_id = Path(library.root_path), library.id
        with open_library_directory(root) as directory:
            info = os.fstat(directory)
        return UploadTarget(library_id, root, spec.filename, info.st_dev, info.st_ino)

    def prepare(
        self, upload_id: str, spec: UploadSpec, target: UploadTarget, source: Path
    ) -> UploadPublication:
        descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as handle:
            content = handle.read(12 * 1024**2 + 1)
        try:
            prepared = self.publication.prepare(
                source_node_id="mcp-" + upload_id, content=content
            )
        except ValueError as error:
            raise UploadError("INVALID_COVER_IMAGE") from error
        fd = os.open(prepared.temporary_path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
            identity = file_identity(os.fstat(fd))
        finally:
            os.close(fd)
        directory = os.open(
            prepared.final_path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        )
        try:
            os.fsync(directory)
            info = os.fstat(directory)
        finally:
            os.close(directory)
        location = UploadTarget(
            target.library_id,
            prepared.final_path.parent,
            prepared.final_path.name,
            info.st_dev,
            info.st_ino,
        )
        return UploadPublication(
            location, prepared.temporary_path.name, identity, prepared.stored_path
        )

    def publish(self, publication: UploadPublication) -> None:
        target = publication.target
        final = target.root / target.relative_path
        staged = target.root / publication.staged_name
        if final.exists():
            observed = file_identity(final.stat())
            expected = publication.identity
            if (observed.device, observed.inode, observed.size, observed.mtime_ns) == (
                expected.device,
                expected.inode,
                expected.size,
                expected.mtime_ns,
            ):
                return
            raise UploadError("UPLOAD_PUBLICATION_CONFLICT")
        if file_identity(staged.stat()) != publication.identity:
            raise UploadError("UPLOAD_STAGING_CHANGED")
        prepared = PreparedSourceNodeCover(
            staged, final, publication.stored_cover_path or ""
        )
        published = self.publication.publish(prepared, previous_stored_path=None)
        self.publication.complete(published, previous_stored_path=None)
        directory = os.open(final.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def discard(
        self,
        upload_id: str,
        target: UploadTarget,
        publication: UploadPublication | None,
    ) -> None:
        # Also catches a crash after prepare but before the journal checkpoint.
        directory = self.root / "covers" / "source-nodes"
        for staged in directory.glob(f".mcp-{upload_id}.*.part"):
            staged.unlink(missing_ok=True)

    def register(
        self, actor: UploadActor, spec: UploadSpec, publication: UploadPublication
    ) -> UploadOutcome:
        before = require_uploaded_cover(
            actor,
            spec,
            self.metadata.snapshot("book", spec.book_id or "", actor.library_ids),
        )
        path = publication.stored_cover_path
        if path is None:
            raise UploadError("INVALID_COVER_IMAGE")
        try:
            self.metadata.apply_uploaded_cover(before, path)
        except MetadataPatchError as error:
            raise UploadError("METADATA_CONFLICT") from error
        reference = "cover:" + hashlib.sha256(path.encode()).hexdigest()
        self.metadata.record(
            MetadataPatchActor(
                actor.user_id,
                actor.grant_id,
                actor.library_ids,
                True,
                False,
                actor.can_override,
            ),
            (
                PreparedMetadataPatch(
                    before, {"cover_ref": reference}, resolved_cover_path=path
                ),
            ),
        )
        after = self.metadata.snapshot("book", before.book_id, actor.library_ids)
        if after is None:
            raise UploadError("RESOURCE_NOT_FOUND")
        return UploadOutcome(
            "COMPLETED",
            book_ids=(before.book_id,),
            revision=after.revision,
            cover_url=f"/api/books/{quote(before.book_id, safe='')}/cover?v={after.revision}",
        )

    def progress(
        self, spec: UploadSpec, target: UploadTarget, outcome: UploadOutcome
    ) -> UploadOutcome:
        return outcome
