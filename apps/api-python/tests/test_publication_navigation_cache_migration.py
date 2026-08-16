from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic import command
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.runner import _run_alembic, head_revision
from app.db.sqlite import create_sqlite_engine
from app.models.library import (
    LibraryFile,
    LibraryMediaVersion,
    LibraryReadingUnit,
    LibraryVolume,
    LibraryWork,
)


def _volume(
    *,
    volume_id: str,
    media_id: str,
    source_format: str,
    chapter_count: int,
) -> tuple[LibraryMediaVersion, LibraryVolume, LibraryFile]:
    media = LibraryMediaVersion(
        id=media_id,
        work_id="navigation-migration-work",
        media_kind=source_format,
    )
    volume = LibraryVolume(
        id=volume_id,
        media_version_id=media.id,
        title=source_format,
        sort_order=0,
        format=source_format,
        resource_key=f"migration:{volume_id}",
        import_status="COMPLETED",
        chapter_count=chapter_count,
    )
    source = LibraryFile(
        id=f"{volume_id}-file",
        volume_id=volume.id,
        path=f"/library/{volume_id}.{source_format.lower()}",
        fingerprint=f"{volume_id}-fingerprint",
        full_hash=(volume_id[0] * 64),
        hash_status="COMPLETED",
        mtime_ms=1,
        kind=source_format,
        mime_type="application/octet-stream",
        size_bytes=1,
        sort_order=0,
    )
    return media, volume, source


def test_0024_upgrade_clears_only_reflowable_chapters_and_adds_empty_cache_state(
    tmp_path: Path,
) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_sqlite_engine(settings.database_path)
    try:
        _run_alembic(
            engine,
            lambda config: command.upgrade(
                config, "0023_publication_full_hash_identity"
            ),
        )
        epub = _volume(
            volume_id="epub-volume",
            media_id="epub-media",
            source_format="EPUB",
            chapter_count=7,
        )
        pdf = _volume(
            volume_id="pdf-volume",
            media_id="pdf-media",
            source_format="PDF",
            chapter_count=5,
        )
        audio = _volume(
            volume_id="audio-volume",
            media_id="audio-media",
            source_format="MP3",
            chapter_count=3,
        )
        with Session(engine) as session:
            session.add(
                LibraryWork(
                    id="navigation-migration-work",
                    origin="MANUAL",
                    title="Migration",
                    normalized_title="migration",
                    author=None,
                    normalized_author=None,
                    tags="[]",
                )
            )
            session.flush()
            for media, _volume_row, _source in (epub, pdf, audio):
                session.add(media)
            session.flush()
            for _media, volume, _source in (epub, pdf, audio):
                session.add(volume)
            session.flush()
            for _media, _volume_row, source in (epub, pdf, audio):
                session.add(source)
            session.flush()
            session.add_all(
                [
                    LibraryReadingUnit(
                        id="epub-chapter",
                        volume_id="epub-volume",
                        file_id="epub-volume-file",
                        unit_type="chapter",
                        title="旧章节",
                        href="chapter.xhtml",
                        sort_order=0,
                        metadata_json="{}",
                    ),
                    LibraryReadingUnit(
                        id="epub-page",
                        volume_id="epub-volume",
                        file_id="epub-volume-file",
                        unit_type="page",
                        title="Page 1",
                        href="page-1",
                        sort_order=0,
                        metadata_json="{}",
                    ),
                    LibraryReadingUnit(
                        id="pdf-page",
                        volume_id="pdf-volume",
                        file_id="pdf-volume-file",
                        unit_type="page",
                        title="Page 1",
                        href="page-1",
                        sort_order=0,
                        metadata_json="{}",
                    ),
                    LibraryReadingUnit(
                        id="audio-chapter",
                        volume_id="audio-volume",
                        file_id="audio-volume-file",
                        unit_type="audio_chapter",
                        title="Track 1",
                        href="track-1",
                        sort_order=0,
                        metadata_json="{}",
                    ),
                ]
            )
            session.commit()

        _run_alembic(
            engine,
            lambda config: command.upgrade(config, "0024_publication_navigation_cache"),
        )
        with Session(engine) as session:
            session.add(
                LibraryReadingUnit(
                    id="epub-projection-v1",
                    volume_id="epub-volume",
                    file_id="epub-volume-file",
                    unit_type="chapter",
                    title="Publication v1",
                    href="chapter.xhtml",
                    sort_order=0,
                    metadata_json='{"hrefBase":"publication-root"}',
                )
            )
            session.get(LibraryVolume, "epub-volume").chapter_count = 1
            session.commit()
        metadata = sa.MetaData()
        cache = sa.Table(
            "PublicationNavigationCache",
            metadata,
            autoload_with=engine,
        )
        with engine.begin() as connection:
            connection.execute(
                sa.insert(cache).values(
                    volumeId="epub-volume",
                    fileId="epub-volume-file",
                    originalFileHash="sha256:" + "e" * 64,
                    parser="epub-package:1",
                    normalization="shuku-epub-locator-dom-v2",
                    chapterCount=1,
                    updatedAt=1,
                )
            )

        _run_alembic(engine, lambda config: command.upgrade(config, "head"))
        _run_alembic(engine, lambda config: command.upgrade(config, "head"))

        assert head_revision(engine) == "0028_remove_publication_render_cache"
        assert "PublicationNavigationCache" in inspect(engine).get_table_names()
        assert "PublicationRenderCache" not in inspect(engine).get_table_names()
        with Session(engine) as session:
            assert session.get(LibraryReadingUnit, "epub-chapter") is None
            assert session.get(LibraryReadingUnit, "epub-page") is not None
            assert session.get(LibraryReadingUnit, "pdf-page") is not None
            assert session.get(LibraryReadingUnit, "audio-chapter") is not None
            assert session.get(LibraryReadingUnit, "epub-projection-v1") is not None
            assert session.get(LibraryVolume, "epub-volume").chapter_count == 1
            assert session.get(LibraryVolume, "pdf-volume").chapter_count == 5
            assert session.get(LibraryVolume, "audio-volume").chapter_count == 3
            cache_table = next(
                table
                for table in inspect(engine).get_table_names()
                if table == "PublicationNavigationCache"
            )
            assert cache_table == "PublicationNavigationCache"
        cache_v2 = sa.Table(
            "PublicationNavigationCache",
            sa.MetaData(),
            autoload_with=engine,
        )
        with engine.connect() as connection:
            projection_version = connection.scalar(
                sa.select(cache_v2.c.projectionVersion).where(
                    cache_v2.c.volumeId == "epub-volume"
                )
            )
            assert projection_version == 1
    finally:
        engine.dispose()
