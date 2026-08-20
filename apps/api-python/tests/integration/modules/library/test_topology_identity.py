from __future__ import annotations

from pathlib import Path

import pytest
from app.core.config import Settings
from app.db.bootstrap import bootstrap_database
from app.db.sqlite import create_sqlite_engine
from app.models.library import Library, LibraryVersion, LibraryVolume, LibraryWork
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


def _new_work(work_id: str) -> LibraryWork:
    return LibraryWork(
        id=work_id,
        library_id="library",
        origin="SCAN",
        source_key="work:book",
        title="Book",
        normalized_title="book",
        tags="[]",
    )


def test_path_topology_keys_are_unique_within_their_parent(tmp_path: Path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    bootstrap_database(engine, settings)

    try:
        with Session(engine) as db, db.begin():
            db.add(
                Library(
                    id="library",
                    name="Library",
                    root_path=str(tmp_path / "books"),
                    organization_mode="VOLUMES",
                )
            )
        with Session(engine) as db, db.begin():
            db.add(_new_work("work-1"))
        with Session(engine) as db, pytest.raises(IntegrityError), db.begin():
            db.add(_new_work("work-2"))

        with Session(engine) as db, db.begin():
            db.add(
                LibraryVersion(
                    id="version",
                    work_id="work-1",
                    source_key="version:book/default",
                )
            )
        with Session(engine) as db, db.begin():
            db.add(
                LibraryVolume(
                    id="volume-1",
                    version_id="version",
                    origin="SCAN",
                    title="Volume",
                    format="EPUB",
                    resource_key="volume:book/default/volume.epub",
                )
            )
        with Session(engine) as db, pytest.raises(IntegrityError), db.begin():
            db.add(
                LibraryVolume(
                    id="volume-2",
                    version_id="version",
                    origin="SCAN",
                    title="Volume duplicate",
                    format="EPUB",
                    resource_key="volume:book/default/volume.epub",
                )
            )
    finally:
        engine.dispose()
