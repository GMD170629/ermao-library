"""Typed Book metadata snapshots, bounded source reads and guarded writes."""

import json
from collections.abc import Callable
from dataclasses import fields, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.contracts.local_metadata_snapshot import (
    LocalMetadataObservation,
    decode_observations,
    merge_observations,
)
from app.contracts.publication_metadata import PublicationMetadata
from app.core.config import Settings
from app.infrastructure.local_metadata_policy import SqlAlchemyLocalMetadataPriority
from app.models import (
    Library,
    LibraryBook,
    LibraryBookMetadata,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
    LibrarySourceNode,
    LibrarySourceNodeMetadata,
)
from app.modules.library.application.facet_sync import prepare_book_facet
from app.modules.library.application.imported_book_metadata import (
    IdentifiedBookMetadata,
    ImportedBookSnapshot,
)
from app.modules.library.application.metadata_ownership import protected_fields
from app.modules.library.domain.facets import normalize_facet_name
from app.modules.library.infrastructure.book_covers import first_readable_resource_id
from app.modules.library.infrastructure.facet_sync import (
    execute_book_facet_write,
    load_book_facet_projections,
    prepare_book_facet_write,
)
from app.modules.library.infrastructure.local_cover_validation import valid_local_cover
from app.modules.media.public import versioned_cover_url
from app.modules.metadata.public import (
    LocalMetadataCandidate,
    metadata_from_source_name,
    resolve_local_metadata,
)


class BookSidecarReader(Protocol):
    def __call__(
        self, source: Path, *, directory: bool
    ) -> LocalMetadataCandidate | None: ...


class SqlAlchemyImportedBookMetadata:
    def __init__(
        self,
        db: Session,
        settings: Settings,
        source_reader: BookSidecarReader,
        idle_check: Callable[[str], bool],
        resolve_cover_path: Callable[[str | None], Path | None],
    ) -> None:
        self._db = db
        self._settings = settings
        self._read_sidecar = source_reader
        self._idle_check = idle_check
        self._resolve_cover_path = resolve_cover_path
        self._priority = SqlAlchemyLocalMetadataPriority(db)

    def load(self, source_node_id: str) -> ImportedBookSnapshot | None:
        row = self._db.execute(
            select(LibraryBook, LibraryBookMetadata, LibrarySourceNode, Library)
            .join(LibraryBookMetadata)
            .join(LibrarySourceNode, LibrarySourceNode.id == LibraryBook.source_node_id)
            .join(Library, Library.id == LibraryBook.library_id)
            .where(LibraryBook.source_node_id == source_node_id)
        ).one_or_none()
        if row is None:
            return None
        book, metadata, node, library = row
        if not metadata.metadata_pending or not self._idle_check(book.id):
            return None
        resources = self._db.scalars(
            select(LibraryReadableResource.id).where(
                LibraryReadableResource.book_id == book.id,
                LibraryReadableResource.enablement_state == "ENABLED",
            )
        ).all()
        observations: tuple[LocalMetadataObservation, ...] = ()
        if len(resources) == 1:
            assets = self._db.scalars(
                select(LibraryResourceAsset)
                .where(
                    LibraryResourceAsset.resource_id == resources[0],
                    LibraryResourceAsset.import_state == "READY",
                )
                .order_by(
                    LibraryResourceAsset.sequence_index.asc().nulls_last(),
                    func.lower(LibraryResourceAsset.sort_key),
                    LibraryResourceAsset.id,
                )
            )
            observations = tuple(
                candidate
                for asset in assets
                for candidate in decode_observations(asset.local_metadata_candidates)
            )
        first = first_readable_resource_id(self._db, book.id)
        cover = self._db.get(LibraryReadableResourceMetadata, first) if first else None
        metadata.metadata_state = "RUNNING"
        self._db.flush()
        self._db.refresh(metadata)
        return ImportedBookSnapshot(
            book.id,
            node.id,
            metadata.import_revision,
            metadata.protected_fields,
            library.root_path,
            node.relative_path,
            node.physical_kind == "DIRECTORY",
            self._priority.load(),
            observations,
            cover.cover_path if cover and cover.cover_status == "READY" else None,
            metadata.cover_path,
            "cover_path" in protected_fields(metadata.protected_fields),
            metadata.updated_at,
        )

    def inspect(self, snapshot: ImportedBookSnapshot) -> IdentifiedBookMetadata:
        root = Path(snapshot.root_path).resolve()
        source = (root / snapshot.relative_path).resolve()
        source.relative_to(root)
        sidecar = self._read_sidecar(source, directory=snapshot.is_directory)
        grouped = merge_observations(
            tuple(
                candidate
                for candidate in snapshot.observations
                if candidate.source != "PATH"
            )
        )
        if sidecar is not None:
            previous = grouped.get("SIDECAR_OPF", PublicationMetadata())
            grouped["SIDECAR_OPF"] = replace(
                sidecar.metadata,
                **{
                    field.name: getattr(previous, field.name)
                    for field in fields(PublicationMetadata)
                    if getattr(sidecar.metadata, field.name) in (None, "", ())
                },
            )
        grouped["PATH"] = metadata_from_source_name(
            Path(snapshot.relative_path).name, is_directory=snapshot.is_directory
        )
        candidates = tuple(
            LocalMetadataCandidate(
                source=kind,
                metadata=grouped[kind],
                cover=sidecar.cover if sidecar and kind == "SIDECAR_OPF" else None,
            )
            for kind in snapshot.priority
            if kind in grouped
        )
        result = resolve_local_metadata(candidates, snapshot.priority)
        cover = valid_local_cover(result.cover)
        if cover is None and not snapshot.cover_protected:
            cover = self._read_cover(snapshot.resource_cover_path)
        return IdentifiedBookMetadata(result.metadata, cover)

    def _read_cover(self, stored_path: str | None) -> bytes | None:
        if not versioned_cover_url("/cover", stored_path, self._settings):
            return None
        path = self._resolve_cover_path(stored_path)
        if path is None:
            return None
        try:
            with path.open("rb") as stream:
                content = stream.read(10 * 1024 * 1024 + 1)
            return valid_local_cover(content)
        except OSError:
            return None

    def still_current(self, snapshot: ImportedBookSnapshot) -> bool:
        self._db.expire_all()
        metadata = self._db.get(LibraryBookMetadata, snapshot.book_id)
        return bool(
            metadata
            and metadata.metadata_pending
            and metadata.import_revision == snapshot.revision
            and metadata.protected_fields == snapshot.protected_fields
            and metadata.updated_at == snapshot.metadata_updated_at
            and self._priority.load() == snapshot.priority
            and self._idle_check(snapshot.book_id)
        )

    def apply(
        self,
        snapshot: ImportedBookSnapshot,
        result: IdentifiedBookMetadata,
        cover_path: str | None,
    ) -> None:
        metadata = self._db.get(LibraryBookMetadata, snapshot.book_id)
        if metadata is None:
            raise LookupError(snapshot.book_id)
        protected = protected_fields(metadata.protected_fields)
        title = result.metadata.title or (
            Path(snapshot.relative_path).name
            if snapshot.is_directory
            else Path(snapshot.relative_path).stem
        )
        values = {
            "title": title,
            "author": result.metadata.author,
            "description": result.metadata.description,
            "series_name": result.metadata.series_name,
            "series_index": result.metadata.series_index,
        }
        for field, value in values.items():
            if field not in protected:
                setattr(metadata, field, value)
        metadata.normalized_title = normalize_facet_name(metadata.title)
        metadata.normalized_author = (
            normalize_facet_name(metadata.author) if metadata.author else None
        )
        if "cover_path" not in protected:
            metadata.cover_path = cover_path
            metadata.cover_status = "READY" if cover_path else "PENDING"
            node = self._db.get(LibrarySourceNodeMetadata, snapshot.source_node_id)
            if node is None:
                node = LibrarySourceNodeMetadata(source_node_id=snapshot.source_node_id)
                self._db.add(node)
            if "cover_path" not in protected_fields(node.protected_fields):
                node.cover_path = cover_path
                node.cover_status = metadata.cover_status
        metadata.processed_revision = snapshot.revision
        metadata.metadata_pending = False
        metadata.metadata_state = "COMPLETED"
        self._db.flush()
        projection = load_book_facet_projections(self._db, (snapshot.book_id,))[0]
        if "tags" not in protected:
            projection = replace(
                projection,
                tags_source=json.dumps(result.metadata.subjects, ensure_ascii=False),
            )
        execute_book_facet_write(
            self._db,
            prepare_book_facet_write(
                (prepare_book_facet(projection),), now=datetime.now(UTC)
            ),
        )
