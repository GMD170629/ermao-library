from __future__ import annotations

import json
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import command
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.runner import _run_alembic, head_revision
from app.db.sqlite import create_sqlite_engine
from app.models.auth import User
from app.models.library import (
    LibraryMediaVersion,
    LibraryReadingProgress,
    LibraryVolume,
)


def test_reader_progress_upgrade_rewrites_legacy_extra_to_v3_location(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_sqlite_engine(settings.database_path)
    try:
        _run_alembic(
            engine,
            lambda config: command.upgrade(config, "0015_management_query_indexes"),
        )
        legacy_work = sa.Table("LibraryWork", sa.MetaData(), autoload_with=engine)
        legacy_file = sa.Table("LibraryFile", sa.MetaData(), autoload_with=engine)
        legacy_progress = sa.Table(
            "LibraryReadingProgress", sa.MetaData(), autoload_with=engine
        )
        with Session(engine) as session, session.begin():
            user = User(
                id="migration-user",
                email="migration@example.com",
                name="Migration reader",
                password_hash="not-used",
                role="admin",
            )
            now = datetime.now(UTC)
            session.execute(
                sa.insert(legacy_work).values(
                    id="migration-work",
                    title="Migration work",
                    normalizedTitle="migration work",
                    author="Author",
                    normalizedAuthor="author",
                    tags="[]",
                    createdAt=now,
                    updatedAt=now,
                )
            )
            media = LibraryMediaVersion(
                id="migration-media",
                work_id="migration-work",
                media_kind="EBOOK",
            )
            volume = LibraryVolume(
                id="migration-volume",
                media_version_id=media.id,
                title="Migration volume",
                sort_order=0,
                format="TXT",
                resource_key="migration:volume",
                import_status="COMPLETED",
            )
            session.add(user)
            session.flush()
            session.add(media)
            session.flush()
            session.add(volume)
            session.flush()
            comic_volume = LibraryVolume(
                id="migration-comic",
                media_version_id=media.id,
                title="Migration comic",
                sort_order=1,
                format="CBZ",
                resource_key="migration:comic",
                import_status="COMPLETED",
            )
            pdf_volume = LibraryVolume(
                id="migration-pdf",
                media_version_id=media.id,
                title="Migration PDF",
                sort_order=2,
                format="PDF",
                resource_key="migration:pdf",
                import_status="COMPLETED",
            )
            audio_volume = LibraryVolume(
                id="migration-audio",
                media_version_id=media.id,
                title="Migration audio",
                sort_order=3,
                format="MP3",
                resource_key="migration:audio",
                import_status="COMPLETED",
            )
            session.add_all([comic_volume, pdf_volume, audio_volume])
            session.flush()
            session.execute(
                sa.insert(legacy_file).values(
                    id="migration-audio-file",
                    volumeId=audio_volume.id,
                    path="/library/migration.mp3",
                    kind="AUDIO",
                    mimeType="audio/mpeg",
                    sortOrder=0,
                    createdAt=now,
                    updatedAt=now,
                )
            )
            session.execute(
                sa.insert(legacy_progress),
                [
                    {
                        "id": "migration-progress",
                        "userId": user.id,
                        "volumeId": volume.id,
                        "readerType": "reflowable",
                        "position": "0",
                        "page": None,
                        "percent": 12.5,
                        "extra": json.dumps(
                            {
                                "sourceFormat": "txt",
                                "currentHref": "txt-section:9",
                                "navigationKey": "migration-unit-9",
                                "chapterIndex": 9,
                                "chapterTitle": "第9章",
                                "sectionIndex": 9,
                            }
                        ),
                        "schemaVersion": 1,
                        "createdAt": now,
                        "updatedAt": now,
                    },
                    {
                        "id": "migration-comic-progress",
                        "userId": user.id,
                        "volumeId": comic_volume.id,
                        "readerType": "comic",
                        "position": "0",
                        "page": 4,
                        "percent": 25,
                        "extra": "{}",
                        "schemaVersion": 1,
                        "createdAt": now,
                        "updatedAt": now,
                    },
                    {
                        "id": "migration-pdf-progress",
                        "userId": user.id,
                        "volumeId": pdf_volume.id,
                        "readerType": "pdf",
                        "position": "0",
                        "page": 7,
                        "percent": 35,
                        "extra": "{}",
                        "schemaVersion": 1,
                        "createdAt": now,
                        "updatedAt": now,
                    },
                    {
                        "id": "migration-audio-progress",
                        "userId": user.id,
                        "volumeId": audio_volume.id,
                        "readerType": "audio",
                        "position": "45000",
                        "page": None,
                        "percent": 40,
                        "extra": "{}",
                        "schemaVersion": 1,
                        "createdAt": now,
                        "updatedAt": now,
                    },
                ],
            )

        _run_alembic(engine, lambda config: command.upgrade(config, "head"))

        with Session(engine) as session:
            migrated = session.scalar(
                select(LibraryReadingProgress).where(
                    LibraryReadingProgress.id == "migration-progress"
                )
            )
            assert migrated is not None
            assert migrated.schema_version == 3
            assert migrated.location_type == "reflowable"
            assert migrated.extra == "{}"
            assert json.loads(migrated.location_json or "{}") == {
                "type": "reflowable",
                "volumeId": "migration-volume",
                "format": "txt",
                "progression": 0.125,
                "href": "txt-section:9",
                "foliate": {
                    "toc": {
                        "index": 9,
                        "title": "第9章",
                        "href": "txt-section:9",
                        "navigationKey": "migration-unit-9",
                    },
                    "section": {"current": 9},
                },
            }
            migrated_locations = {
                progress.id: json.loads(progress.location_json or "{}")
                for progress in session.scalars(
                    select(LibraryReadingProgress).where(
                        LibraryReadingProgress.id.in_(
                            [
                                "migration-comic-progress",
                                "migration-pdf-progress",
                                "migration-audio-progress",
                            ]
                        )
                    )
                )
            }
            assert migrated_locations == {
                "migration-comic-progress": {
                    "type": "comic",
                    "volumeId": "migration-comic",
                    "pageIndex": 4,
                },
                "migration-pdf-progress": {
                    "type": "pdf",
                    "volumeId": "migration-pdf",
                    "pageNumber": 7,
                },
                "migration-audio-progress": {
                    "type": "audio",
                    "volumeId": "migration-audio",
                    "fileId": "migration-audio-file",
                    "positionMs": 45000,
                },
            }
            assert head_revision(engine) == "0026_publication_render_cache"
    finally:
        engine.dispose()
