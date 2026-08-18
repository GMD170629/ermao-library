from __future__ import annotations

import inspect
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.library import (
    LibraryFile,
    LibraryMediaVersion,
    LibraryVersion,
    LibraryVolume,
    LibraryWork,
)
from app.modules.library.domain.version_identity import IMPLICIT_VERSION_SOURCE_KEY
from app.modules.publications.application.ports import PublicationAccessScope
from app.modules.publications.domain.model import PublicationCorruptError
from app.modules.publications.infrastructure.source_files import (
    resolve_publication_source,
)
from app.modules.publications.infrastructure.source_repository import (
    SqlAlchemyPublicationSourceRepository,
)
from app.modules.reader.application.dto import ReaderAccessScope
from app.modules.reader.infrastructure.volume_repository import (
    SqlAlchemyReaderVolumeRepository,
)

_API_ROOT = Path(__file__).resolve().parents[4]
_READER_ROOT = _API_ROOT / "app" / "modules" / "reader"
_SOURCE_REPOSITORY = (
    _API_ROOT
    / "app"
    / "modules"
    / "publications"
    / "infrastructure"
    / "source_repository.py"
)
_AUDIOBOOK_SUPPORT_TEST = _API_ROOT / "tests" / "test_audiobook_support.py"
_ADMIN_PUBLICATION = PublicationAccessScope(
    is_admin=True,
    can_view_manual_imports=True,
    library_ids=(),
)
_ADMIN_READER = ReaderAccessScope(
    is_admin=True,
    can_view_manual_imports=True,
    library_ids=(),
)


def _production_python_sources() -> list[Path]:
    return [
        *_READER_ROOT.rglob("*.py"),
        _SOURCE_REPOSITORY,
    ]


def _seed_catalog(
    db: Session,
    *,
    work_id: str,
    version_id: str,
    media_id: str | None,
    media_kind: str,
    volume_id: str,
    title: str,
    fmt: str,
    files: tuple[tuple[str, str, str, str, int], ...],
) -> LibraryVolume:
    work = db.get(LibraryWork, work_id)
    if work is None:
        work = LibraryWork(
            library_id="test-library",
            id=work_id,
            origin="MANUAL",
            title=title,
            normalized_title=title.lower(),
            author="作者",
            normalized_author="作者",
            tags="[]",
        )
        db.add(work)
        db.flush()
    version = db.get(LibraryVersion, version_id)
    if version is None:
        version = LibraryVersion(
            id=version_id,
            work_id=work_id,
            source_key=IMPLICIT_VERSION_SOURCE_KEY,
        )
        db.add(version)
        db.flush()
    if media_id is not None and db.get(LibraryMediaVersion, media_id) is None:
        db.add(
            LibraryMediaVersion(
                id=media_id,
                work_id=work_id,
                media_kind=media_kind,
            )
        )
        db.flush()
    volume = LibraryVolume(
        id=volume_id,
        version_id=version.id,
        title=title,
        sort_order=0,
        format=fmt,
        resource_key=f"manual:{volume_id}",
        import_status="COMPLETED",
    )
    db.add(volume)
    db.flush()
    for file_id, path, kind, mime_type, sort_order in files:
        db.add(
            LibraryFile(
                id=file_id,
                volume_id=volume.id,
                path=path,
                mtime_ms=1,
                kind=kind,
                mime_type=mime_type,
                size_bytes=4,
                sort_order=sort_order,
            )
        )
    db.commit()
    return volume


def test_reader_production_queries_do_not_use_volume_media_version_id() -> None:
    violations = [
        str(path.relative_to(_API_ROOT))
        for path in _production_python_sources()
        if "LibraryVolume.media_version_id" in path.read_text(encoding="utf-8")
    ]
    assert violations == []


def test_reader_source_lookup_does_not_query_library_media_version() -> None:
    source = _SOURCE_REPOSITORY.read_text(encoding="utf-8")
    assert "LibraryMediaVersion" not in source
    context_source = inspect.getsource(SqlAlchemyReaderVolumeRepository.get_context)
    assert "LibraryVersion.id == LibraryVolume.version_id" in context_source
    assert "LibraryWork.id == LibraryVersion.work_id" in context_source
    assert "LibraryVolume.media_version_id" not in context_source


def test_audiobook_support_tests_do_not_reference_removed_file_hashes() -> None:
    source = _AUDIOBOOK_SUPPORT_TEST.read_text(encoding="utf-8")
    assert "LibraryFile.fingerprint" not in source
    assert "`fingerprint`" not in source
    assert "`hashStatus`" not in source
    assert "`fullHash`" not in source
    assert "hash_status" not in source
    assert "full_hash" not in source


@pytest.mark.parametrize(
    ("fmt", "kind", "mime", "media_kind", "path_name"),
    [
        ("EPUB", "EPUB", "application/epub+zip", "EBOOK", "book.epub"),
        ("PDF", "PDF", "application/pdf", "EBOOK", "book.pdf"),
        ("CBZ", "CBZ", "application/vnd.comicbook+zip", "COMIC", "book.cbz"),
        ("AZW3", "AZW3", "application/x-mobipocket-ebook", "EBOOK", "book.azw3"),
    ],
)
def test_reader_resolves_work_and_source_through_library_version(
    db_session: Session,
    tmp_path: Path,
    fmt: str,
    kind: str,
    mime: str,
    media_kind: str,
    path_name: str,
) -> None:
    source_path = tmp_path / path_name
    source_path.write_bytes(b"src")
    suffix = fmt.lower()
    volume = _seed_catalog(
        db_session,
        work_id=f"work-{suffix}",
        version_id=f"version-{suffix}",
        media_id=f"media-{suffix}",
        media_kind=media_kind,
        volume_id=f"volume-{suffix}",
        title=f"{fmt} 卷册",
        fmt=fmt,
        files=((f"file-{suffix}", str(source_path), kind, mime, 0),),
    )

    context = SqlAlchemyReaderVolumeRepository(db_session).get_context(volume.id)
    source = SqlAlchemyPublicationSourceRepository(db_session).find_source(
        volume_id=volume.id,
        access_scope=_ADMIN_PUBLICATION,
    )

    assert context is not None
    assert context.work.id == f"work-{suffix}"
    assert context.volume.id == volume.id
    assert source is not None
    assert source.volume_id == volume.id
    assert source.path == str(source_path)
    assert source.source_format == fmt.lower()


def test_audiobook_lists_every_track_in_sort_order_without_media_version_per_file(
    db_session: Session,
    tmp_path: Path,
) -> None:
    first = tmp_path / "z-last-name.mp3"
    second = tmp_path / "a-first-name.mp3"
    first.write_bytes(b"one")
    second.write_bytes(b"two")
    volume = _seed_catalog(
        db_session,
        work_id="work-audio",
        version_id="version-audio",
        media_id="media-audio",
        media_kind="AUDIOBOOK",
        volume_id="volume-audio",
        title="有声书",
        fmt="AUDIO",
        files=(
            ("file-audio-1", str(first), "AUDIO", "audio/mpeg", 0),
            ("file-audio-2", str(second), "AUDIO", "audio/mpeg", 1),
        ),
    )

    repository = SqlAlchemyReaderVolumeRepository(db_session)
    context = repository.get_context(volume.id)
    files = repository.list_files(volume.id)
    source = SqlAlchemyPublicationSourceRepository(db_session).find_source(
        volume_id=volume.id,
        access_scope=_ADMIN_PUBLICATION,
    )

    assert context is not None
    assert context.work.id == "work-audio"
    assert [file.id for file in files] == ["file-audio-1", "file-audio-2"]
    assert [file.sort_order for file in files] == [0, 1]
    assert source is not None
    assert source.file_id == "file-audio-1"
    assert source.path == str(first)


def test_reader_source_lookup_does_not_require_library_media_version(
    db_session: Session,
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "orphan.epub"
    source_path.write_bytes(b"epub")
    volume = _seed_catalog(
        db_session,
        work_id="work-orphan",
        version_id="version-orphan",
        media_id=None,
        media_kind="EBOOK",
        volume_id="volume-orphan",
        title="无媒体版本",
        fmt="EPUB",
        files=(("file-orphan", str(source_path), "EPUB", "application/epub+zip", 0),),
    )

    source = SqlAlchemyPublicationSourceRepository(db_session).find_source(
        volume_id=volume.id,
        access_scope=_ADMIN_PUBLICATION,
    )
    files = SqlAlchemyReaderVolumeRepository(db_session).list_files(volume.id)

    assert source is not None
    assert source.path == str(source_path)
    assert [file.id for file in files] == ["file-orphan"]


def test_missing_source_file_keeps_unavailable_error(
    db_session: Session,
    test_settings: Settings,
    tmp_path: Path,
) -> None:
    missing = tmp_path / "gone.epub"
    volume = _seed_catalog(
        db_session,
        work_id="work-missing",
        version_id="version-missing",
        media_id="media-missing",
        media_kind="EBOOK",
        volume_id="volume-missing",
        title="缺失源文件",
        fmt="EPUB",
        files=(("file-missing", str(missing), "EPUB", "application/epub+zip", 0),),
    )
    source = SqlAlchemyPublicationSourceRepository(db_session).find_source(
        volume_id=volume.id,
        access_scope=_ADMIN_PUBLICATION,
    )

    assert source is not None
    with pytest.raises(PublicationCorruptError, match="unavailable"):
        resolve_publication_source(source.path, test_settings.resolved_storage_root)
    assert (
        SqlAlchemyReaderVolumeRepository(db_session)
        .list_visible_volumes_for_work(
            "work-missing",
            _ADMIN_READER,
        )[0]
        .id
        == volume.id
    )
