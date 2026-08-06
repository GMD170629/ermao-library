from __future__ import annotations

import json

from alembic import command
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.runner import _run_alembic, head_revision
from app.db.sqlite import create_sqlite_engine
from app.models.auth import User
from app.models.library import (
    LibraryFile,
    LibraryMediaVersion,
    LibraryReadingProgress,
    LibraryVolume,
    LibraryWork,
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
        with Session(engine) as session, session.begin():
            user = User(
                id="migration-user",
                email="migration@example.com",
                name="Migration reader",
                password_hash="not-used",
                role="admin",
            )
            work = LibraryWork(
                id="migration-work",
                title="Migration work",
                normalized_title="migration work",
                author="Author",
                normalized_author="author",
                tags="[]",
            )
            media = LibraryMediaVersion(
                id="migration-media",
                work_id=work.id,
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
            session.add(work)
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
            session.add(
                LibraryFile(
                    id="migration-audio-file",
                    volume_id=audio_volume.id,
                    path="/library/migration.mp3",
                    kind="AUDIO",
                    mime_type="audio/mpeg",
                    sort_order=0,
                )
            )
            progress = LibraryReadingProgress(
                id="migration-progress",
                user_id=user.id,
                volume_id=volume.id,
                reader_type="reflowable",
                position="0",
                percent=12.5,
                extra=json.dumps(
                    {
                        "sourceFormat": "txt",
                        "currentHref": "txt-section:9",
                        "navigationKey": "migration-unit-9",
                        "chapterIndex": 9,
                        "chapterTitle": "第9章",
                        "sectionIndex": 9,
                    }
                ),
                schema_version=1,
                location_type=None,
                location_json=None,
            )
            session.add_all(
                [
                    progress,
                    LibraryReadingProgress(
                        id="migration-comic-progress",
                        user_id=user.id,
                        volume_id=comic_volume.id,
                        reader_type="comic",
                        position="0",
                        page=4,
                        percent=25,
                        extra="{}",
                        schema_version=1,
                    ),
                    LibraryReadingProgress(
                        id="migration-pdf-progress",
                        user_id=user.id,
                        volume_id=pdf_volume.id,
                        reader_type="pdf",
                        position="0",
                        page=7,
                        percent=35,
                        extra="{}",
                        schema_version=1,
                    ),
                    LibraryReadingProgress(
                        id="migration-audio-progress",
                        user_id=user.id,
                        volume_id=audio_volume.id,
                        reader_type="audio",
                        position="45000",
                        percent=40,
                        extra="{}",
                        schema_version=1,
                    ),
                ]
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
            assert head_revision(engine) == "0016_reader_progress_v3"
    finally:
        engine.dispose()
