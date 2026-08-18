from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.bootstrap.imports import import_managed_book
from app.models.library import (
    LibraryFile,
    LibraryMediaVersion,
    LibraryMetadata,
    LibraryReadingUnit,
    LibraryVersion,
    LibraryVolume,
    LibraryWork,
)
from app.modules.library.domain.version_identity import IMPLICIT_VERSION_SOURCE_KEY
from tests.test_audiobook_support import _import_audio_fixture
from tests.test_worker_importer import (
    _options,
    write_comic_fixture,
    write_epub_fixture,
    write_epub_metadata_fixture,
    write_pdf_fixture,
)


def _implicit_version(db_session: Session, work_id: str) -> LibraryVersion:
    version = db_session.scalar(
        select(LibraryVersion).where(
            LibraryVersion.work_id == work_id,
            LibraryVersion.source_key == IMPLICIT_VERSION_SOURCE_KEY,
        )
    )
    assert version is not None
    return version


def _assert_volume_uses_implicit_version(
    db_session: Session, *, work_id: str, volume_id: str | None
) -> LibraryVersion:
    assert volume_id is not None
    version = _implicit_version(db_session, work_id)
    volume = db_session.get(LibraryVolume, volume_id)
    assert volume is not None
    assert volume.version_id == version.id
    media_ids = set(
        db_session.scalars(
            select(LibraryMediaVersion.id).where(LibraryMediaVersion.work_id == work_id)
        )
    )
    assert version.id not in media_ids
    return version


def test_epub_import_creates_implicit_version_and_volume_version_id(
    db_session: Session, test_settings, tmp_path: Path
) -> None:
    test_settings.resolved_storage_root.mkdir(parents=True)
    epub = tmp_path / "implicit-epub.epub"
    write_epub_fixture(epub)
    result = import_managed_book(
        db_session,
        test_settings,
        _options(source_file_path=epub, origin="MANUAL", original_name=epub.name),
    )
    _assert_volume_uses_implicit_version(
        db_session, work_id=result.work_id, volume_id=result.volume_id
    )
    assert db_session.scalar(select(func.count()).select_from(LibraryFile)) == 1
    assert db_session.scalar(select(func.count()).select_from(LibraryMetadata)) >= 1


def test_pdf_import_creates_implicit_version_and_volume_version_id(
    db_session: Session, test_settings, tmp_path: Path
) -> None:
    test_settings.resolved_storage_root.mkdir(parents=True)
    pdf = tmp_path / "implicit.pdf"
    write_pdf_fixture(pdf)
    result = import_managed_book(
        db_session,
        test_settings,
        _options(source_file_path=pdf, origin="MANUAL", original_name=pdf.name),
    )
    _assert_volume_uses_implicit_version(
        db_session, work_id=result.work_id, volume_id=result.volume_id
    )


def test_comic_import_creates_implicit_version(
    db_session: Session, test_settings, tmp_path: Path
) -> None:
    test_settings.resolved_storage_root.mkdir(parents=True)
    comic = tmp_path / "implicit.zip"
    write_comic_fixture(comic)
    result = import_managed_book(
        db_session,
        test_settings,
        _options(source_file_path=comic, origin="MANUAL", original_name=comic.name),
    )
    _assert_volume_uses_implicit_version(
        db_session, work_id=result.work_id, volume_id=result.volume_id
    )
    assert db_session.scalar(select(func.count()).select_from(LibraryReadingUnit)) == 2


def test_audio_import_creates_implicit_version(
    db_session: Session, test_settings, monkeypatch, tmp_path: Path
) -> None:
    test_settings.resolved_storage_root.mkdir(parents=True)
    result, _audio_dir = _import_audio_fixture(
        db_session, test_settings, monkeypatch, tmp_path
    )
    _assert_volume_uses_implicit_version(
        db_session, work_id=result.work_id, volume_id=result.volume_id
    )


def test_text_import_creates_implicit_version(
    db_session: Session, test_settings, tmp_path: Path
) -> None:
    test_settings.resolved_storage_root.mkdir(parents=True)
    source = tmp_path / "implicit.txt"
    source.write_text("第一章\n正文。", encoding="utf-8")
    result = import_managed_book(
        db_session,
        test_settings,
        _options(source_file_path=source, origin="MANUAL", original_name=source.name),
    )
    _assert_volume_uses_implicit_version(
        db_session, work_id=result.work_id, volume_id=result.volume_id
    )


def test_multiple_imports_of_same_work_share_one_implicit_version(
    db_session: Session, test_settings, tmp_path: Path
) -> None:
    test_settings.resolved_storage_root.mkdir(parents=True)
    first = tmp_path / "同一作品 1.epub"
    second = tmp_path / "同一作品 2.epub"
    write_epub_fixture(first)
    write_epub_fixture(second)
    first_result = import_managed_book(
        db_session,
        test_settings,
        _options(source_file_path=first, origin="WATCH", original_name=first.name),
    )
    second_result = import_managed_book(
        db_session,
        test_settings,
        _options(source_file_path=second, origin="WATCH", original_name=second.name),
    )
    assert first_result.work_id == second_result.work_id
    assert first_result.volume_id != second_result.volume_id
    first_version = _assert_volume_uses_implicit_version(
        db_session, work_id=first_result.work_id, volume_id=first_result.volume_id
    )
    second_version = _assert_volume_uses_implicit_version(
        db_session, work_id=second_result.work_id, volume_id=second_result.volume_id
    )
    assert first_version.id == second_version.id
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(LibraryVersion)
            .where(LibraryVersion.work_id == first_result.work_id)
        )
        == 1
    )


def test_different_media_kinds_share_one_implicit_version(
    db_session: Session, test_settings, tmp_path: Path
) -> None:
    test_settings.resolved_storage_root.mkdir(parents=True)
    epub = tmp_path / "[混排][作者].epub"
    comic = tmp_path / "[混排][作者].zip"
    write_epub_metadata_fixture(epub, "混排", "作者")
    write_comic_fixture(comic)
    epub_result = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=epub,
            origin="MANUAL",
            original_name=epub.name,
            requested_title="混排",
            requested_author="作者",
        ),
    )
    comic_result = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=comic,
            origin="MANUAL",
            original_name=comic.name,
            requested_title="混排",
            requested_author="作者",
        ),
    )
    assert epub_result.work_id == comic_result.work_id
    epub_version = _assert_volume_uses_implicit_version(
        db_session, work_id=epub_result.work_id, volume_id=epub_result.volume_id
    )
    comic_version = _assert_volume_uses_implicit_version(
        db_session, work_id=comic_result.work_id, volume_id=comic_result.volume_id
    )
    assert epub_version.id == comic_version.id
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(LibraryMediaVersion)
            .where(LibraryMediaVersion.work_id == epub_result.work_id)
        )
        == 2
    )


def test_retry_import_does_not_create_duplicate_version(
    db_session: Session, test_settings, tmp_path: Path
) -> None:
    test_settings.resolved_storage_root.mkdir(parents=True)
    source = tmp_path / "retry.epub"
    write_epub_fixture(source)
    first = import_managed_book(
        db_session,
        test_settings,
        _options(source_file_path=source, origin="MANUAL", original_name=source.name),
    )
    second = import_managed_book(
        db_session,
        test_settings,
        _options(source_file_path=source, origin="MANUAL", original_name=source.name),
    )
    assert second.duplicate is True
    assert first.work_id == second.work_id
    assert db_session.scalar(select(func.count()).select_from(LibraryWork)) == 1
    assert db_session.scalar(select(func.count()).select_from(LibraryVersion)) == 1
    _assert_volume_uses_implicit_version(
        db_session, work_id=first.work_id, volume_id=first.volume_id
    )
