"""Composition-owned observer for metadata-to-OPF side effects."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import event, inspect, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.models.library import LibraryMediaVersion, LibraryVolume, LibraryWork
from app.services.metadata_file_writeback import schedule_work_metadata_writebacks

WORK_FIELDS = frozenset(
    {"title", "author", "description", "tags", "series_name", "series_index", "cover_path"}
)
VOLUME_FIELDS = frozenset(
    {
        "title",
        "volume_index",
        "description",
        "language",
        "publisher",
        "published_at",
        "identifier",
        "isbn",
        "narrator",
        "abridged",
        "cover_path",
        "media_version_id",
    }
)


def _changed(instance: object, fields: Iterable[str]) -> bool:
    state = inspect(instance)
    return state.pending or any(state.attrs[field].history.has_changes() for field in fields)


def _changed_work_ids(db: Session) -> set[str]:
    work_ids = {
        entity.id
        for entity in db.new.union(db.dirty)
        if isinstance(entity, LibraryWork) and _changed(entity, WORK_FIELDS)
    }
    volume_media_ids = {
        entity.media_version_id
        for entity in db.new.union(db.dirty)
        if isinstance(entity, LibraryVolume) and _changed(entity, VOLUME_FIELDS)
    }
    media_entities = {
        entity
        for entity in db.new.union(db.dirty)
        if isinstance(entity, LibraryMediaVersion)
        and _changed(entity, {"work_id", "media_kind"})
    }
    work_ids.update(entity.work_id for entity in media_entities)
    for entity in media_entities:
        history = inspect(entity).attrs.work_id.history
        work_ids.update(str(value) for value in history.deleted if value)
    if volume_media_ids:
        work_ids.update(
            db.scalars(
                select(LibraryMediaVersion.work_id).where(
                    LibraryMediaVersion.id.in_(volume_media_ids)
                )
            ).all()
        )
    return {work_id for work_id in work_ids if work_id}


def install_metadata_opf_observer(
    factory: sessionmaker[Session], settings: Settings
) -> None:
    """Install once on a process-owned session factory."""
    if getattr(factory, "_shuku_metadata_opf_observer", False):
        return

    def after_flush(db: Session, _flush_context: object) -> None:
        pending = db.info.setdefault("metadata_opf_changed_work_ids", set())
        if isinstance(pending, set):
            pending.update(_changed_work_ids(db))

    def before_commit(db: Session) -> None:
        if db.info.get("metadata_opf_observer_running"):
            return
        explicit = db.info.get("metadata_opf_scheduled_work_ids", set())
        explicit_work_ids = explicit if isinstance(explicit, set) else set()
        pending = db.info.get("metadata_opf_changed_work_ids", set())
        pending_work_ids = pending if isinstance(pending, set) else set()
        work_ids = pending_work_ids.union(_changed_work_ids(db)).difference(
            explicit_work_ids
        )
        if not work_ids:
            return
        db.info["metadata_opf_observer_running"] = True
        try:
            db.flush()
            for work_id in sorted(work_ids):
                schedule_work_metadata_writebacks(
                    db,
                    work_id=work_id,
                    source="METADATA_OBSERVER",
                    settings=settings,
                )
        finally:
            db.info.pop("metadata_opf_observer_running", None)

    def clear_state(db: Session) -> None:
        db.info.pop("metadata_opf_changed_work_ids", None)
        db.info.pop("metadata_opf_scheduled_work_ids", None)
        db.info.pop("metadata_opf_observer_running", None)

    event.listen(factory, "after_flush", after_flush)
    event.listen(factory, "before_commit", before_commit)
    event.listen(factory, "after_commit", clear_state)
    event.listen(factory, "after_rollback", clear_state)
    factory._shuku_metadata_opf_observer = True
