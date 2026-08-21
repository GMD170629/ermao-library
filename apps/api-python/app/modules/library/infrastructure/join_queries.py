"""Typed Version-to-Resource joins for library adapters."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    LibraryResourceAsset,
    ReadableResourceNavigationUnit,
    LibraryReadableResource,
    LibraryReadableResource,
)
from app.modules.library.domain.media_kinds import media_kind_of
from app.modules.library.infrastructure.books import entity_record


def get_volume_context(db: Session, resource_id: str) -> dict[str, Any] | None:
    row = db.execute(
        select(LibraryReadableResource, LibraryReadableResource)
        .join(
            LibraryReadableResource,
            LibraryReadableResource.id == LibraryReadableResource.resource_id,
        )
        .where(LibraryReadableResource.id == resource_id)
    ).first()
    if row is None:
        return None
    volume, version = row
    payload = entity_record(volume)
    payload.update(
        bookId=version.book_id,
        mediaKind=media_kind_of(volume),
        resourceId=version.id,
    )
    return payload


def get_unit_context(db: Session, unit_id: str) -> dict[str, Any] | None:
    row = db.execute(
        select(ReadableResourceNavigationUnit, LibraryReadableResource, LibraryReadableResource)
        .join(LibraryReadableResource, LibraryReadableResource.id == ReadableResourceNavigationUnit.resource_id)
        .join(
            LibraryReadableResource,
            LibraryReadableResource.id == LibraryReadableResource.resource_id,
        )
        .where(ReadableResourceNavigationUnit.id == unit_id)
    ).first()
    if row is None:
        return None
    unit, volume, version = row
    payload = entity_record(unit)
    payload.update(
        bookId=version.book_id,
        mediaKind=media_kind_of(volume),
        resourceId=version.id,
        format=volume.format,
    )
    return payload


def list_file_paths_for_work(db: Session, book_id: str) -> list[str]:
    paths = db.scalars(
        select(LibraryResourceAsset.path)
        .join(LibraryReadableResource, LibraryReadableResource.id == LibraryResourceAsset.resource_id)
        .join(
            LibraryReadableResource,
            LibraryReadableResource.id == LibraryReadableResource.resource_id,
        )
        .where(LibraryReadableResource.book_id == book_id)
    ).all()
    return [str(path) for path in paths if path]


def get_volume_for_work(
    db: Session, *, resource_id: str, book_id: str
) -> dict[str, Any] | None:
    row = db.execute(
        select(LibraryReadableResource, LibraryReadableResource)
        .join(
            LibraryReadableResource,
            LibraryReadableResource.id == LibraryReadableResource.resource_id,
        )
        .where(
            LibraryReadableResource.id == resource_id,
            LibraryReadableResource.book_id == book_id,
            LibraryReadableResource.hidden.is_(False),
        )
    ).first()
    if row is None:
        return None
    volume, version = row
    payload = entity_record(volume)
    payload.update(
        sourceWorkId=version.book_id,
        sourceFormat=volume.format,
        resourceId=version.id,
    )
    return payload


def get_volume_belonging_to_work(
    db: Session, *, resource_id: str, book_id: str
) -> dict[str, Any] | None:
    return get_volume_for_work(db, resource_id=resource_id, book_id=book_id)
